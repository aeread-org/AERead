from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import IntEnum
from fractions import Fraction
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

    assert canonical_json_bytes(frozen) == (
        b'{"nested":{"items":[{"price":5}]}}'
    )
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
    assert adapter.dump_python(value, mode="json") == {
        "nested": [1, {"ok": True}]
    }


def test_public_records_are_frozen_and_normalize_lists_to_tuples() -> None:
    channel = ActionChannel(
        channel_id="offers",
        recipient_seat_ids=["seller1"],
        action_schema_ref="offer/1",
    )
    assert channel.recipient_seat_ids == ("seller1",)
    with pytest.raises(ValidationError):
        channel.channel_id = "changed"


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
    assert isinstance(
        round_tripped.references["baseline"], ComparisonBaselineReference
    )
    assert isinstance(
        round_tripped.references["support_min"], OutcomeSupportReference
    )


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
        terminal=TerminalResult(
            status="terminal", reason="allocated", final_state={}
        ),
        outcome=FamilyOutcome(
            terminal_reason="allocated", payload={}, utility_by_seat={}
        ),
        evidence=_evidence(),
    )
    assert execution.status == "ok"


def test_sdk_import_does_not_load_family_or_integration_modules() -> None:
    code = """
import sys
import aeread.sdk.v1
assert 'aeread.exchange_economy' not in sys.modules
assert not any(name.startswith('aeread.integrations') for name in sys.modules)
"""
    repo_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
