from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import IntEnum
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import BaseModel, ValidationError

from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    ActionEnvelope,
    AgentContext,
    ArtifactRef,
    AttemptBudget,
    CanonicalResponse,
    CanonicalizationError,
    DecisionSlot,
    EventIdentity,
    EpisodeExecutionResult,
    EvaluationReceipt,
    FamilyOutcome,
    FrozenJSONDict,
    ImplementationRef,
    LegalityResult,
    MetricValue,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    ScoreEnvelope,
    SealedEvidenceView,
    TerminalResult,
    TransitionResult,
    ValidityReport,
    canonical_json_bytes,
    content_sha256,
    validate_action_bundle,
)


class _IntegerEnum(IntEnum):
    ONE = 1


class _IntegerSubclass(int):
    pass


class _FloatSubclass(float):
    pass


class _StringSubclass(str):
    pass


def _channel(
    channel_id: str = "buyer1-seller1",
    *,
    min_actions: int = 1,
    max_actions: int | None = 1,
) -> ActionChannel:
    return ActionChannel(
        channel_id=channel_id,
        recipient_seat_ids=("seller1",),
        action_schema_ref="offer/1",
        min_actions=min_actions,
        max_actions=max_actions,
    )


def _slot(*channels: ActionChannel) -> DecisionSlot:
    return DecisionSlot(
        slot_id="buyer1-round0",
        seat_id="buyer1",
        channels=channels or (_channel(),),
        observation_schema_ref="obs/1",
        response_schema_ref="reply/1",
        order_key="0001",
    )


def _action(
    action_id: str = "offer-1",
    *,
    slot_id: str = "buyer1-round0",
    channel_id: str = "buyer1-seller1",
    actor_seat_id: str = "buyer1",
    sequence_index: int = 0,
) -> ActionEnvelope:
    return ActionEnvelope(
        action_id=action_id,
        slot_id=slot_id,
        channel_id=channel_id,
        actor_seat_id=actor_seat_id,
        sequence_index=sequence_index,
        payload={"price": 5},
    )


def _implementation() -> ImplementationRef:
    return ImplementationRef(
        implementation_id="fake_scorer",
        version="1.0.0",
        content_sha256="1" * 64,
    )


def _score(*, references: dict[str, object] | None = None) -> ScoreEnvelope:
    return ScoreEnvelope(
        status="ok",
        measurement_kind="optimizable_outcome",
        direction="maximize",
        bound_status=None,
        primary=MetricValue(value=5.0, unit="usd"),
        metrics={"welfare": MetricValue(value=5.0, unit="usd")},
        utility_by_seat={"buyer1": 5.0},
        capture_by_seat={"buyer1": 5.0},
        references=references or {},
        outcome={"allocated": True},
        validity=ValidityReport(status="valid"),
        scorer=_implementation(),
        oracle=None,
        evidence_refs=("event-1",),
    )


def _evidence() -> SealedEvidenceView:
    return SealedEvidenceView(
        identity=EventIdentity(
            run_plan_id="plan-1",
            cell_id="cell-1",
            episode_id="episode-1",
            episode_attempt_id="attempt-1",
        ),
        evidence_store_id="a" * 32,
        events=(),
        artifacts=(),
        event_root_sha256="2" * 64,
        artifact_root_sha256="3" * 64,
    )


def _receipt() -> EvaluationReceipt:
    return EvaluationReceipt(
        status="ok",
        run_plan_id="plan-1",
        cell_id="cell-1",
        episode_id="episode-1",
        episode_attempt_id="attempt-1",
        cluster_id="cluster-1",
        run_plan_sha256="4" * 64,
        case_sha256="5" * 64,
        agent_config_sha256="6" * 64,
        implementations=(_implementation(),),
        evidence=_evidence(),
        score=_score(),
        inclusion_status="included",
        replay_level="deterministic",
    )


def test_decision_slot_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DecisionSlot.model_validate(
            {
                "slot_id": "buyer1-round0",
                "seat_id": "buyer1",
                "channels": [],
                "observation_schema_ref": "obs/1",
                "response_schema_ref": "reply/1",
                "order_key": "0001",
                "typo": True,
            }
        )


def test_canonical_hash_is_key_order_independent() -> None:
    assert content_sha256({"b": 2, "a": 1}) == content_sha256({"a": 1, "b": 2})


def test_canonical_bytes_are_compact_sorted_utf8() -> None:
    assert canonical_json_bytes({"z": "市场", "a": [2, 1]}) == (
        b'{"a":[2,1],"z":"\xe5\xb8\x82\xe5\x9c\xba"}'
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_bytes_reject_non_finite_float(value: float) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"value": value})


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        {"nested": {1: "x"}},
        {"unsupported": object()},
        {"unsupported": {1, 2}},
    ],
)
def test_canonical_bytes_reject_values_outside_strict_json(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(value)


def test_non_string_json_keys_cannot_collide_with_string_keys() -> None:
    with pytest.raises(CanonicalizationError):
        content_sha256({1: "x"})
    assert content_sha256({"1": "x"})


def test_canonicalization_rejects_pydantic_json_coercion() -> None:
    class CoercingModel(BaseModel):
        occurred_at: datetime

    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(CoercingModel(occurred_at=datetime(2026, 8, 24)))


def test_action_payload_rejects_non_string_keys_and_unsupported_values() -> None:
    with pytest.raises(ValidationError):
        ActionEnvelope(
            action_id="bad-key",
            slot_id="buyer1-round0",
            channel_id="buyer1-seller1",
            actor_seat_id="buyer1",
            sequence_index=0,
            payload={1: "x"},
        )
    with pytest.raises(ValidationError):
        ActionEnvelope(
            action_id="bad",
            slot_id="buyer1-round0",
            channel_id="buyer1-seller1",
            actor_seat_id="buyer1",
            sequence_index=0,
            payload={"bad": object()},
        )


def test_nested_json_payload_is_deeply_immutable_and_hash_stable() -> None:
    source = {"nested": {"price": 5}, "items": [{"id": "a"}]}
    action = ActionEnvelope(
        action_id="offer-1",
        slot_id="buyer1-round0",
        channel_id="buyer1-seller1",
        actor_seat_id="buyer1",
        sequence_index=0,
        payload=source,
    )
    digest = content_sha256(action)

    source["nested"]["price"] = 99
    source["items"].append({"id": "b"})
    with pytest.raises(TypeError):
        action.payload["nested"]["price"] = 7
    with pytest.raises(AttributeError):
        action.payload["items"].append({"id": "c"})

    assert action.payload["nested"]["price"] == 5
    assert action.model_dump(mode="json")["payload"] == {
        "nested": {"price": 5},
        "items": [{"id": "a"}],
    }
    assert content_sha256(action) == digest


def test_prebuilt_frozen_json_is_recursive_and_hash_stable() -> None:
    source = {"nested": {"items": [{"price": 5}]}}
    frozen = FrozenJSONDict(source)
    direct_digest = content_sha256(frozen)
    action = ActionEnvelope(
        action_id="offer-1",
        slot_id="buyer1-round0",
        channel_id="buyer1-seller1",
        actor_seat_id="buyer1",
        sequence_index=0,
        payload=frozen,
    )
    record_digest = content_sha256(action)

    source["nested"]["items"][0]["price"] = 99
    with pytest.raises(AttributeError):
        frozen["nested"]["items"].append({"price": 7})
    with pytest.raises(TypeError):
        frozen["nested"]["items"][0]["price"] = 7

    assert canonical_json_bytes(frozen) == (b'{"nested":{"items":[{"price":5}]}}')
    assert content_sha256(frozen) == direct_digest
    assert content_sha256(action) == record_digest


@pytest.mark.parametrize(
    "value",
    [
        {1: "x"},
        {"unsupported": object()},
        {"non_finite": float("nan")},
    ],
)
def test_frozen_json_constructor_rejects_invalid_json(value: object) -> None:
    with pytest.raises(ValueError):
        FrozenJSONDict(value)


@pytest.mark.parametrize(
    ("exotic", "native"),
    [
        (Decimal("1"), 1),
        (Fraction(1, 1), 1),
        (_IntegerEnum.ONE, 1),
        (_IntegerSubclass(1), 1),
        (_FloatSubclass(1.0), 1.0),
        (_StringSubclass("one"), "one"),
    ],
)
def test_canonicalization_rejects_non_builtin_scalars_with_native_equivalents(
    exotic: object, native: object
) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"value": exotic})
    with pytest.raises(CanonicalizationError):
        content_sha256({"value": exotic})
    assert canonical_json_bytes({"value": native})
    assert content_sha256({"value": native})


def test_json_object_type_has_an_object_schema_and_plain_json_dump() -> None:
    from pydantic import TypeAdapter

    from aeread.sdk.v1 import JSONObject

    adapter = TypeAdapter(JSONObject)
    assert adapter.json_schema()["type"] == "object"
    value = adapter.validate_python({"nested": [1, {"ok": True}]})
    assert adapter.dump_python(value, mode="json") == {"nested": [1, {"ok": True}]}


def test_public_records_are_frozen_and_normalize_lists_to_tuples() -> None:
    channel = ActionChannel(
        channel_id="offers",
        recipient_seat_ids=["seller1"],
        action_schema_ref="offer/1",
    )
    assert channel.recipient_seat_ids == ("seller1",)
    with pytest.raises(ValidationError):
        channel.channel_id = "changed"


def test_plan_cell_is_the_only_stable_planning_record_export() -> None:
    import aeread.sdk.v1 as sdk_v1

    assert sdk_v1.EpisodeCell is sdk_v1.PlanCell
    assert "PlanCell" in sdk_v1.__all__
    assert "EpisodeCell" not in sdk_v1.__all__
    assert sdk_v1.PlanCell.__name__ == "PlanCell"


@pytest.mark.parametrize(
    ("record_factory", "field_names"),
    [
        (lambda: CanonicalResponse(), ("usage",)),
        (
            lambda: AgentContext(
                agent_profile_id="agent-1",
                seat_id="buyer1",
                provider="provider",
                model="model",
                harness="harness",
                runtime="runtime",
            ),
            ("metadata",),
        ),
        (lambda: ParseResult(status="malformed"), ("diagnostics",)),
        (lambda: TransitionResult(state={}, next_phase_id=None), ("evidence",)),
        (
            lambda: FamilyOutcome(terminal_reason="done", payload={}),
            ("utility_by_seat",),
        ),
        (lambda: MetricValue(value=1.0), ("metadata",)),
        (
            _score,
            (
                "metrics",
                "utility_by_seat",
                "capture_by_seat",
                "references",
                "outcome",
            ),
        ),
        (_receipt, ("trajectory_refs",)),
    ],
)
def test_record_mappings_are_immutable_even_when_defaults_are_omitted(
    record_factory: object, field_names: tuple[str, ...]
) -> None:
    record = record_factory()
    digest = content_sha256(record)
    for field_name in field_names:
        mapping = getattr(record, field_name)
        with pytest.raises(TypeError):
            mapping["mutation"] = "forbidden"
    assert content_sha256(record) == digest


def test_every_record_serializes_and_hashes_its_version() -> None:
    action = _action()
    dumped = action.model_dump(mode="json")
    assert dumped["spec_version"] == "aeread.sdk_record/1"
    assert content_sha256(action) != content_sha256(
        {key: value for key, value in dumped.items() if key != "spec_version"}
    )


def test_record_rejects_a_wrong_serialized_version() -> None:
    payload = _action().model_dump(mode="json")
    payload["spec_version"] = "aeread.sdk_record/2"
    with pytest.raises(ValidationError):
        ActionEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            ActionEnvelope,
            {
                "action_id": "a",
                "slot_id": "s",
                "channel_id": "c",
                "actor_seat_id": "x",
                "sequence_index": "0",
                "payload": {},
            },
        ),
        (MetricValue, {"value": "5"}),
        (
            AttemptBudget,
            {"timeout_seconds": "1.5", "output_token_limit": 8},
        ),
        (
            AttemptBudget,
            {"timeout_seconds": 1.5, "output_token_limit": "8"},
        ),
        (
            ActionChannel,
            {
                "channel_id": "c",
                "recipient_seat_ids": [],
                "action_schema_ref": "action/1",
                "min_actions": "0",
            },
        ),
        (
            ArtifactRef,
            {"sha256": "a" * 64, "media_type": "text/plain", "size_bytes": "1"},
        ),
        (
            PluginManifest,
            {
                "plugin_id": b"plugin",
                "plugin_version": "1.0.0",
                "sdk_api": "aeread.sdk/v1",
            },
        ),
    ],
)
def test_public_scalar_fields_reject_coercible_non_json_source_types(
    model: type, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "field_name", "base_payload", "exotic_values"),
    [
        (
            ActionEnvelope,
            "sequence_index",
            {
                "action_id": "a",
                "slot_id": "s",
                "channel_id": "c",
                "actor_seat_id": "x",
                "sequence_index": 0,
                "payload": {},
            },
            (_IntegerEnum.ONE, _IntegerSubclass(1)),
        ),
        (
            MetricValue,
            "value",
            {"value": 1.0},
            (
                Decimal("1"),
                Fraction(1, 1),
                _IntegerEnum.ONE,
                _IntegerSubclass(1),
                _FloatSubclass(1.0),
            ),
        ),
        (
            PluginManifest,
            "plugin_id",
            {
                "plugin_id": "plugin",
                "plugin_version": "1.0.0",
                "sdk_api": "aeread.sdk/v1",
            },
            (_StringSubclass("plugin"),),
        ),
    ],
)
def test_public_scalars_require_exact_builtin_source_types(
    model: type,
    field_name: str,
    base_payload: dict[str, object],
    exotic_values: tuple[object, ...],
) -> None:
    for exotic in exotic_values:
        payload = {**base_payload, field_name: exotic}
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            ActionEnvelope,
            {
                "spec_version": _StringSubclass("aeread.sdk_record/1"),
                "action_id": "a",
                "slot_id": "s",
                "channel_id": "c",
                "actor_seat_id": "x",
                "sequence_index": 0,
                "payload": {},
            },
        ),
        (
            PluginManifest,
            {
                "plugin_id": "plugin",
                "plugin_version": "1.0.0",
                "sdk_api": _StringSubclass("aeread.sdk/v1"),
            },
        ),
        (
            PhaseSpec,
            {
                "phase_id": "phase",
                "actor_selector": "actors",
                "mode": _StringSubclass("single"),
                "observation_schema_by_role": {},
                "action_schema_by_role": {},
                "max_logical_actions": 1,
                "invalid_action_policy": "forfeit",
                "next_phases": (),
            },
        ),
        (ParseResult, {"status": _StringSubclass("malformed")}),
    ],
)
def test_string_literal_fields_require_exact_builtin_strings(
    model: type, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_json_arrays_still_load_into_tuple_fields() -> None:
    slot = DecisionSlot.model_validate_json(
        """
        {
          "slot_id": "buyer1-round0",
          "seat_id": "buyer1",
          "channels": [{
            "channel_id": "offers",
            "recipient_seat_ids": ["seller1"],
            "action_schema_ref": "offer/1"
          }],
          "observation_schema_ref": "obs/1",
          "response_schema_ref": "reply/1",
          "order_key": "0001"
        }
        """
    )
    assert isinstance(slot.channels, tuple)
    assert isinstance(slot.channels[0].recipient_seat_ids, tuple)


def test_plugin_manifest_accepts_only_v1_sdk_api() -> None:
    manifest = PluginManifest(
        plugin_id="fake_market",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )
    assert manifest.sdk_api == "aeread.sdk/v1"
    with pytest.raises(ValidationError):
        PluginManifest(
            plugin_id="fake_market",
            plugin_version="1.0.0",
            sdk_api="aeread.sdk/v2",
        )


def test_action_channel_rejects_impossible_cardinality() -> None:
    with pytest.raises(ValidationError):
        _channel(min_actions=2, max_actions=1)


def test_decision_slot_rejects_duplicate_channel_ids() -> None:
    with pytest.raises(ValidationError):
        _slot(_channel(), _channel())


@pytest.mark.parametrize(
    "actions",
    [
        (_action(), _action(sequence_index=1)),
        (_action(), _action("offer-2")),
        (_action(sequence_index=1), _action("offer-2", sequence_index=0)),
        (_action(), _action("offer-2", slot_id="other", sequence_index=1)),
        (_action(), _action("offer-2", actor_seat_id="buyer2", sequence_index=1)),
    ],
)
def test_action_bundle_rejects_broken_intrinsic_identity_or_order(
    actions: tuple[ActionEnvelope, ...],
) -> None:
    with pytest.raises(ValidationError):
        ActionBundle(slot_id="buyer1-round0", actions=actions)


def test_bundle_validation_rejects_an_undeclared_channel() -> None:
    bundle = ActionBundle(
        slot_id="buyer1-round0",
        actions=(_action(channel_id="buyer1-seller2"),),
    )
    with pytest.raises(ValueError, match="undeclared channel"):
        validate_action_bundle(bundle, _slot())


def test_bundle_validation_enforces_channel_minimum_and_maximum() -> None:
    required = _channel(min_actions=1, max_actions=1)
    with pytest.raises(ValueError, match="requires at least 1"):
        ActionBundle(slot_id="buyer1-round0", actions=()).validate_against(
            _slot(required)
        )

    too_many = ActionBundle(
        slot_id="buyer1-round0",
        actions=(_action(), _action("offer-2", sequence_index=1)),
    )
    with pytest.raises(ValueError, match="allows at most 1"):
        too_many.validate_against(_slot(required))


def test_bundle_validation_checks_slot_and_actor() -> None:
    wrong_slot = ActionBundle(
        slot_id="other-slot",
        actions=(_action(slot_id="other-slot"),),
    )
    with pytest.raises(ValueError, match="slot_id"):
        wrong_slot.validate_against(_slot())

    wrong_actor = ActionBundle(
        slot_id="buyer1-round0",
        actions=(_action(actor_seat_id="buyer2"),),
    )
    with pytest.raises(ValueError, match="actor_seat_id"):
        wrong_actor.validate_against(_slot())


def test_valid_multichannel_bundle_is_returned_unchanged() -> None:
    slot = _slot(
        _channel("buyer1-seller1"),
        _channel("buyer1-seller2", min_actions=0, max_actions=2),
    )
    bundle = ActionBundle(
        slot_id=slot.slot_id,
        actions=(
            _action(),
            _action(
                "offer-2",
                channel_id="buyer1-seller2",
                sequence_index=1,
            ),
        ),
    )
    assert validate_action_bundle(bundle, slot) is bundle


def test_phase_graph_rejects_duplicate_and_undeclared_phase_edges() -> None:
    phase = PhaseSpec(
        phase_id="offer",
        actor_selector="buyers",
        mode="simultaneous",
        observation_schema_by_role={"buyer": "obs/1"},
        action_schema_by_role={"buyer": "reply/1"},
        max_logical_actions=2,
        invalid_action_policy="forfeit",
        next_phases=("settle",),
    )
    with pytest.raises(ValidationError):
        PhaseGraph(initial_phase_id="offer", phases=(phase, phase))
    with pytest.raises(ValidationError):
        PhaseGraph(initial_phase_id="offer", phases=(phase,))


def test_typed_reference_variants_round_trip_through_score_envelope() -> None:
    from aeread.sdk.v1 import (
        ComparisonBaselineReference,
        OptimizationBoundReference,
        OutcomeSupportReference,
    )

    references = {
        "upper": OptimizationBoundReference(
            kind="optimum_upper_bound",
            value=10.0,
            objective_id="allocation_value",
            objective_version="1.0.0",
            units="usd",
            direction="maximize",
            feasible_set="declared allocations",
            information_set="full information",
            horizon="one episode",
            opponent_condition="fixed provider",
            proof_type="exact_solver",
            implementation=_implementation(),
            validity_domain="fixture-v1",
        ),
        "baseline": ComparisonBaselineReference(
            kind="comparison_baseline",
            value=4.0,
            comparison_id="fixed_policy",
            comparison_version="1.0.0",
            units="usd",
            direction="maximize",
            provenance={"case_set": "dev-v1"},
            applicability="fixed provider episodes",
            implementation=_implementation(),
        ),
        "support_min": OutcomeSupportReference(
            kind="outcome_support_min",
            value=0.0,
            objective_id="allocation_value",
            objective_version="1.0.0",
            units="usd",
            direction="maximize",
            feasible_set="declared allocations",
            information_set="full information",
            horizon="one episode",
            opponent_condition="fixed provider",
            proof_type="enumerated_support",
            implementation=_implementation(),
            validity_domain="fixture-v1",
            applicability="fixture-v1",
        ),
    }
    score = _score(references=references)
    round_tripped = ScoreEnvelope.model_validate(score.model_dump(mode="json"))
    assert isinstance(round_tripped.references["upper"], OptimizationBoundReference)
    assert isinstance(round_tripped.references["baseline"], ComparisonBaselineReference)
    assert isinstance(round_tripped.references["support_min"], OutcomeSupportReference)


def test_optimum_upper_bound_requires_every_binding_field() -> None:
    from aeread.sdk.v1 import OptimizationBoundReference

    with pytest.raises(ValidationError):
        OptimizationBoundReference(
            kind="optimum_upper_bound",
            value=10.0,
            implementation=_implementation(),
        )


def test_outcome_support_requires_every_binding_field() -> None:
    from aeread.sdk.v1 import OutcomeSupportReference

    complete = {
        "kind": "outcome_support_max",
        "value": 10.0,
        "objective_id": "allocation_value",
        "objective_version": "1.0.0",
        "units": "usd",
        "direction": "maximize",
        "feasible_set": "declared allocations",
        "information_set": "full information",
        "horizon": "one episode",
        "opponent_condition": "fixed provider",
        "proof_type": "enumerated_support",
        "implementation": _implementation(),
        "validity_domain": "fixture-v1",
        "applicability": "fixture-v1",
    }
    reference = OutcomeSupportReference.model_validate(complete)
    assert reference.kind == "outcome_support_max"

    for field_name in (
        "objective_id",
        "objective_version",
        "units",
        "direction",
        "feasible_set",
        "information_set",
        "horizon",
        "opponent_condition",
        "proof_type",
        "implementation",
        "validity_domain",
        "applicability",
    ):
        missing = {key: value for key, value in complete.items() if key != field_name}
        with pytest.raises(ValidationError):
            OutcomeSupportReference.model_validate(missing)


def test_status_records_reject_unknown_discriminants_from_complete_payloads() -> None:
    records = (
        ParseResult(
            status="ok",
            bundle=ActionBundle(slot_id="buyer1-round0", actions=(_action(),)),
        ),
        LegalityResult(status="legal"),
        TerminalResult(status="terminal", reason="allocated", final_state={}),
        _score(),
        _receipt(),
    )
    for record in records:
        payload = record.model_dump(mode="python")
        payload["status"] = "unknown"
        with pytest.raises(ValidationError):
            type(record).model_validate(payload)


def test_status_consistency_checks_only_settled_record_contracts() -> None:
    with pytest.raises(ValidationError):
        ParseResult(status="ok", bundle=None)
    with pytest.raises(ValidationError):
        ParseResult(
            status="malformed",
            bundle=ActionBundle(slot_id="buyer1-round0", actions=(_action(),)),
        )

    execution = EpisodeExecutionResult(
        status="ok",
        terminal=TerminalResult(status="terminal", reason="allocated", final_state={}),
        outcome=FamilyOutcome(
            terminal_reason="allocated", payload={}, utility_by_seat={}
        ),
        evidence=_evidence(),
    )
    assert execution.status == "ok"


def test_sdk_import_does_not_load_family_or_integration_modules() -> None:
    code = """
import sys

def unexpected_aeread_modules(modules):
    return sorted(
        name
        for name in modules
        if name.startswith('aeread.')
        and name != 'aeread.sdk'
        and not name.startswith('aeread.sdk.')
    )

unexpected_before = unexpected_aeread_modules(sys.modules)
assert not unexpected_before, ('pre-import aeread modules', unexpected_before)

import aeread.sdk.v1

unexpected_after = unexpected_aeread_modules(sys.modules)
assert not unexpected_after, ('post-import aeread modules', unexpected_after)

for forbidden_prefix in (
    'harbor',
    'tau',
    'openai',
    'google',
    'anthropic',
):
    assert not any(
        name.startswith(forbidden_prefix) for name in sys.modules
    ), forbidden_prefix
"""
    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)

    polluted_code = (
        """
import sys
import types
sys.modules['aeread.nonir_classifier'] = types.ModuleType('aeread.nonir_classifier')
"""
        + code
    )
    polluted = subprocess.run(
        [sys.executable, "-c", polluted_code],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert polluted.returncode != 0
    assert "pre-import aeread modules" in polluted.stderr


def test_legacy_measurement_schema_and_content_hashes_are_unchanged() -> None:
    from aeread.sdk.v1 import (
        ComparativeMeasurementSpec,
        ComparisonBaselineContract,
        FamilyManifest,
        OptimizableOutcomeMeasurementSpec,
        PropertyAnswerMeasurementSpec,
    )
    from .fakes import (
        fake_implementation,
        fake_resolution_inputs,
    )

    def digest(value: object) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    family = fake_resolution_inputs().family
    optimizable = family.measurements[0]
    property_spec = PropertyAnswerMeasurementSpec(
        estimand_id="answer_correctness",
        direction="maximize",
        primary_metric_id="correct",
        verifier_plugin_id="fake_verifier",
        verifier_semantics_id="exact_answer",
        verifier_semantics_version="1.0.0",
        measurement_kind="property_or_answer",
        property_definition_id="target_property",
        property_definition_version="1.0.0",
        answer_schema_ref="answer/1",
    )
    comparative = ComparativeMeasurementSpec(
        estimand_id="preference",
        direction="maximize",
        primary_metric_id="preference",
        verifier_plugin_id="fake_verifier",
        verifier_semantics_id="human_preference",
        verifier_semantics_version="1.0.0",
        measurement_kind="comparative_or_human_judged",
        comparison_target_id="candidate",
        comparison_protocol_id="blind_pairwise",
        comparison_protocol_version="1.0.0",
        rater_semantics_id="rubric",
        rater_semantics_version="1.0.0",
        comparison_baseline=ComparisonBaselineContract(
            kind="comparison_baseline",
            comparison_id="human_reference",
            comparison_version="1.0.0",
            provenance={"source": "fixture"},
            objective_id="preference",
            objective_version="1.0.0",
            units="points",
            direction="maximize",
            feasible_set="declared answers",
            information_set="public prompt",
            horizon="one episode",
            opponent_condition="fixed",
            stochastic_expectation="none",
            proof_type="pinned comparator",
            implementation=fake_implementation("human_reference"),
            validity_domain="dev",
            applicability="dev",
        ),
        support_contracts={},
    )

    schema_hashes = {
        model.__name__: digest(model.model_json_schema())
        for model in (
            PropertyAnswerMeasurementSpec,
            OptimizableOutcomeMeasurementSpec,
            ComparativeMeasurementSpec,
            FamilyManifest,
        )
    }
    assert schema_hashes == {
        "PropertyAnswerMeasurementSpec": "b1c81be89fc0c5967a10a625971a728059d166a5ee9ff347419cf2e40a1abeb0",
        "OptimizableOutcomeMeasurementSpec": "ba4d0c393acd464bf52759360e773fc4c58d4e5b19e707967013eff2e5d15dc2",
        "ComparativeMeasurementSpec": "61c01bfbd38dbb7d807d0e0f7471e7c5cdf6ccc4f12de4b16494725f861ce58a",
        "FamilyManifest": "98fceba5ca2d3da831f548b96c464b1a15ba4087c6476bec94aaa8e960a68ee8",
    }
    assert {
        name: digest(record.model_dump(mode="json"))
        for name, record in (
            ("PropertyAnswerMeasurementSpec", property_spec),
            ("OptimizableOutcomeMeasurementSpec", optimizable),
            ("ComparativeMeasurementSpec", comparative),
            ("FamilyManifest", family),
        )
    } == {
        "PropertyAnswerMeasurementSpec": "975d6fd8dd56a37e2bb0de112ebcccb74e14043a9b9439a28c625cb1d085b2e8",
        "OptimizableOutcomeMeasurementSpec": "0200a339b77fbc3b8cdd058855e1a550b4791ddab2e335375c141326548b2174",
        "ComparativeMeasurementSpec": "94f3430c8661e79c0266c52ec31ddb4135cc734c83c5e210999ae5147faf7922",
        "FamilyManifest": "f5aff50f39f667f3b80752953225fcac46c6cf5feb191f0b171625549adf841e",
    }


def test_b1_b2_b3_b4a_additions_preserve_legacy_schema_and_export_abi() -> None:
    import aeread.sdk.v1 as sdk_v1
    from aeread.sdk.v1 import (
        ClusterSpec,
        EvaluationBlock,
        FamilyManifest,
        PlanCell,
        RunPlan,
        SuiteManifest,
    )

    def digest(value: object) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    assert {
        model.__name__: digest(model.model_json_schema())
        for model in (
            ClusterSpec,
            EvaluationBlock,
            SuiteManifest,
            PlanCell,
            RunPlan,
            FamilyManifest,
        )
    } == {
        "ClusterSpec": "e284fac21824ccd795922b685fbbd76f3c2ecfbddb05d47d7264affadc634ec0",
        "EvaluationBlock": "787c63e331b4946b2886952d4705c539104b6786c384d07a8c5652c2d0174a2f",
        "SuiteManifest": "85e16708a5e7695a800448fc28bab618905d7baa1d8ba5e2c41d177409ee0530",
        "PlanCell": "b01e32b42ec0f65a4899fd231197e35ad1b1ad58f2ab115f15879570a697fc25",
        "RunPlan": "0ebd2ef5ffd9a30632bf5a4943e05fa9e90961ca6b1f60c21081ab0d14c2d31a",
        "FamilyManifest": "98fceba5ca2d3da831f548b96c464b1a15ba4087c6476bec94aaa8e960a68ee8",
    }

    planned_identity_exports = {
        "ClusterDesignSpec",
        "ClusterMembershipSpec",
        "EpisodeReplicationDesign",
        "FixedPanelDesignSpec",
        "PairingSpec",
        "PanelDesignSpec",
        "PlannedCoordinateField",
        "SampledPanelDesignSpec",
        "SamplingPopulationSpec",
        "SeededEpisodeReplicationDesign",
        "UnseededEpisodeReplicationDesign",
    }
    measurement_selection_exports = {
        "EvaluationInstrumentSpec",
        "JudgeEvaluationInstrumentSpec",
        "MeasurementSelectionSpec",
        "NoJudgeEvaluationInstrumentSpec",
    }
    execution_design_exports = {
        "EpisodeAttemptPolicySpec",
        "EpisodeTerminalDispositionRule",
        "EvaluatorAgentJudgmentTemplateSpec",
        "ExecutionBlockSpec",
        "ExecutionDesignSpec",
        "ExecutionRecordRef",
        "FixedPanelResolutionTemplateSpec",
        "ImportedHumanJudgmentTemplateSpec",
        "JudgmentWorkTemplateSpec",
        "PanelResolutionTemplateSpec",
        "SampledPanelResolutionTemplateSpec",
    }
    analysis_estimator_missingness_exports = {
        "BooleanSuccessPredicateSpec",
        "BoundsOrSensitivityMissingnessSpec",
        "CanonicalRational",
        "CompleteCaseConditionalMissingnessSpec",
        "DifferenceEstimatorSpec",
        "EpisodeMissingnessSpec",
        "EstimatorSpec",
        "IdentityTransformationSpec",
        "MeanEstimatorSpec",
        "PassAllKEstimatorSpec",
        "PlannedPopulationInvalidateMissingnessSpec",
        "ProbabilityEstimatorSpec",
        "QuantileEstimatorSpec",
        "RaterCoverageSummarySpec",
        "RaterDisagreementSummarySpec",
        "RaterSummarySpec",
    }
    execution_assignment_exports = {
        "AssignmentAuthoringRecordRef",
        "ExchangeabilityDomainSpec",
        "ExecuteUniformWithinPairAssignmentSourceSpec",
        "ExecutionAssignmentSourceSpec",
        "ImportedUniformWithinPairAssignmentSourceSpec",
        "IndependentUniformWithinPairExecutionAssignmentSpec",
    }
    b4b_exports = {
        "AnalysisSourceRef",
        "EffectiveResamplingBlockSpec",
        "PopulationClusterProjectionSpec",
        "PairProjectionSpec",
        "NoIntervalSpec",
        "ClusterBootstrapStabilityIntervalSpec",
        "IntervalSpec",
        "NoHypothesisTestSpec",
        "PairedRandomizationTestSpec",
        "HypothesisTestSpec",
        "NoMultiplicityAdjustmentSpec",
        "HolmMultiplicityAdjustmentSpec",
        "MultiplicityAdjustmentSpec",
        "InferenceCompatibilitySpec",
    }
    added_exports = tuple(
        name for name in sdk_v1.__all__ if name in planned_identity_exports
    )
    assert len(added_exports) == 11
    assert set(added_exports) == planned_identity_exports
    b2_added_exports = tuple(
        name for name in sdk_v1.__all__ if name in measurement_selection_exports
    )
    assert len(b2_added_exports) == 4
    assert set(b2_added_exports) == measurement_selection_exports
    b3_added_exports = tuple(
        name for name in sdk_v1.__all__ if name in execution_design_exports
    )
    assert len(b3_added_exports) == 11
    assert set(b3_added_exports) == execution_design_exports
    b4a_added_exports = tuple(
        name
        for name in sdk_v1.__all__
        if name in analysis_estimator_missingness_exports
    )
    assert len(b4a_added_exports) == 16
    assert set(b4a_added_exports) == analysis_estimator_missingness_exports
    b3b_added_exports = tuple(
        name for name in sdk_v1.__all__ if name in execution_assignment_exports
    )
    assert len(b3b_added_exports) == 6
    assert set(b3b_added_exports) == execution_assignment_exports
    legacy_exports = tuple(
        sorted(
            name
            for name in sdk_v1.__all__
            if name not in planned_identity_exports
            and name not in measurement_selection_exports
            and name not in execution_design_exports
            and name not in analysis_estimator_missingness_exports
            and name not in execution_assignment_exports
            and name not in b4b_exports
        )
    )
    assert len(legacy_exports) == 158
    assert digest(legacy_exports) == (
        "2fe7d6311a309b47d2b753381144e2e7689a11b65e9bac145162ce779565bd3b"
    )
