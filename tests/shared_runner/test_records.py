from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    ActionEnvelope,
    CanonicalizationError,
    DecisionSlot,
    EvaluationReceipt,
    LegalityResult,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    ScoreEnvelope,
    TerminalResult,
    canonical_json_bytes,
    content_sha256,
    validate_action_bundle,
)


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


def test_public_records_are_frozen_and_normalize_lists_to_tuples() -> None:
    channel = ActionChannel(
        channel_id="offers",
        recipient_seat_ids=["seller1"],
        action_schema_ref="offer/1",
    )
    assert channel.recipient_seat_ids == ("seller1",)
    with pytest.raises(ValidationError):
        channel.channel_id = "changed"


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


@pytest.mark.parametrize(
    ("model", "status"),
    [
        (ParseResult, "unknown"),
        (LegalityResult, "unknown"),
        (TerminalResult, "unknown"),
        (ScoreEnvelope, "unknown"),
        (EvaluationReceipt, "unknown"),
    ],
)
def test_status_records_reject_unknown_discriminants(model: type, status: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"status": status})


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
