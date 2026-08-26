from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from aeread import housing_env as native
from aeread.families.housing_v1 import (
    HousingAdapterContractError,
    HousingV1CellBinding,
    HousingV1EnvironmentPlugin,
)
from aeread.families.housing_v1_records import (
    HousingHoldRecord,
    HousingOfferRecord,
    HousingRentRecord,
    HousingStateRecord,
)
from aeread.runner import ArtifactStore, EventStore
from aeread.runner.registry import PluginRegistry, PluginVersionMismatch
from aeread.sdk.v1 import (
    ActionBundle,
    ActionEnvelope,
    CanonicalResponse,
    EnvironmentPlugin,
    EventIdentity,
    canonical_json_bytes,
    content_sha256,
)


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "housing_v1"
    / "e0_seed7_two_tenants_two_listings.json"
)
CASE_ID = "housing-v1-e0-seed7-two-tenant-two-listing"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _slot_by_seat(slots, seat_id: str):
    return next(slot for slot in slots if slot.seat_id == seat_id)


def _slot_by_order_key(slots, order_key: str):
    return next(slot for slot in slots if slot.order_key == order_key)


def _reseal(raw: dict[str, object]) -> dict[str, object]:
    raw["artifact_sha256"] = content_sha256(
        {key: value for key, value in raw.items() if key != "artifact_sha256"}
    )
    return raw


def _rounds_case(rounds: int) -> dict[str, object]:
    raw = _fixture()
    raw["rounds"] = rounds
    references = raw["references"]
    assert isinstance(references, dict)
    horizon = "one_round" if rounds == 1 else f"{rounds}_rounds"
    for name in ("lower", "upper"):
        reference = references[name]
        assert isinstance(reference, dict)
        reference["horizon"] = horizon
    baseline = references["baseline"]
    assert isinstance(baseline, dict)
    provenance = baseline["provenance"]
    assert isinstance(provenance, dict)
    provenance["rounds"] = rounds
    provenance["landlord_policy"] = "scripted"
    provenance["tenant_policy"] = "naive"
    provenance["tenant_population_assignment"] = "all_tenants_naive"
    baseline["applicability"] = (
        "all-naive tenant population against fixed scripted landlords; same "
        "materialized case and round horizon"
    )
    world = native.make_bid_world(2, 2, seed=7, common_weight=0.6)
    baseline["value"] = native.run_scripted_market(
        world, rounds=rounds, strategy="naive"
    ).total
    return _reseal(raw)


def _canonical_value(value: object) -> object:
    return json.loads(canonical_json_bytes(value))


def _canonical_recursive_nodes(value: object) -> tuple[object, ...]:
    canonical = _canonical_value(value)
    nodes: list[object] = []

    def visit(node: object) -> None:
        nodes.append(node)
        if isinstance(node, dict):
            for key, child in node.items():
                nodes.append(key)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(canonical)
    return tuple(nodes)


def _recursive_keys(value: object) -> set[str]:
    canonical = _canonical_value(value)
    keys: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            keys.update(str(key) for key in node)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(canonical)
    return keys


_PUBLIC_BOARD_ROW_KEYS = {
    "listing_id",
    "rent_asked",
    "beds",
    "baths",
    "minutes_to_campus",
    "crime_index",
    "minutes_to_groceries",
    "orientation",
    "status",
}
_OFFER_KEYS = {
    "spec_version",
    "offer_id",
    "tenant_id",
    "listing_id",
    "rent",
    "round_index",
}
_HOLD_KEYS = {
    "spec_version",
    "hold_id",
    "tenant_id",
    "listing_id",
    "rent",
    "round_index",
}
_TENANT_PAYLOAD_KEYS = {
    "role",
    "seat_id",
    "tenant_id",
    "round_index",
    "remaining_rounds",
    "phase",
    "public_board",
    "rejected_listing_ids",
    "active_hold",
    "own_prior_offers",
    "private_values",
}
_LANDLORD_PAYLOAD_KEYS = {
    "role",
    "seat_id",
    "listing_id",
    "round_index",
    "remaining_rounds",
    "phase",
    "public_board",
    "listing",
    "private_cost",
    "inbox",
}


def _assert_public_board_shape(board: object) -> None:
    assert isinstance(board, list)
    assert board
    assert all(isinstance(row, dict) for row in board)
    assert all(set(row) == _PUBLIC_BOARD_ROW_KEYS for row in board)


def _assert_role_payload_privacy(
    case, payload: object, role: str, owner_id: int
) -> None:
    visible = _canonical_value(payload)
    assert isinstance(visible, dict)
    expected_keys = _TENANT_PAYLOAD_KEYS if role == "tenant" else _LANDLORD_PAYLOAD_KEYS
    assert set(visible) == expected_keys
    assert visible["role"] == role
    _assert_public_board_shape(visible["public_board"])

    # Scalar traversal makes the oracle robust to a secret moved under a renamed
    # nested key; field-name deny-lists alone do not establish privacy.
    nodes = _canonical_recursive_nodes(visible)
    if role == "tenant":
        assert visible["tenant_id"] == owner_id
        assert visible["private_values"] == list(case.world.values[owner_id])
        for tenant_id, values in enumerate(case.world.values):
            if tenant_id != owner_id:
                assert list(values) not in nodes
                assert all(value not in nodes for value in values)
        assert all(cost not in nodes for cost in case.world.costs)
        assert all(set(row) == _OFFER_KEYS for row in visible["own_prior_offers"])
        if visible["active_hold"] is not None:
            assert set(visible["active_hold"]) == _HOLD_KEYS
    else:
        assert visible["listing_id"] == owner_id
        assert set(visible["listing"]) == _PUBLIC_BOARD_ROW_KEYS
        assert visible["listing"]["listing_id"] == owner_id
        assert visible["private_cost"] == case.world.costs[owner_id]
        assert all(
            cost not in nodes
            for listing_id, cost in enumerate(case.world.costs)
            if listing_id != owner_id
        )
        assert all(value not in nodes for row in case.world.values for value in row)
        assert all(set(row) == _OFFER_KEYS for row in visible["inbox"])
        assert all(row["listing_id"] == owner_id for row in visible["inbox"])


def _step_with_mapping_order_proof(
    plugin: HousingV1EnvironmentPlugin,
    case,
    state,
    phase,
    bundles: dict[str, ActionBundle],
):
    assert len(bundles) >= 2
    forward = plugin.step(case, state, phase, bundles)
    reversed_pairs = dict(reversed(tuple(bundles.items())))
    assert tuple(reversed_pairs.items()) == tuple(reversed(tuple(bundles.items())))
    backward = plugin.step(case, state, phase, reversed_pairs)
    assert backward == forward
    assert canonical_json_bytes(backward) == canonical_json_bytes(forward)
    assert content_sha256(backward) == content_sha256(forward)
    return forward


def _case_and_state(
    plugin: HousingV1EnvironmentPlugin,
    raw: dict[str, object] | None = None,
):
    materialized = _fixture() if raw is None else raw
    case = plugin.validate_case(materialized)
    state = plugin.initial_state(
        case,
        HousingV1CellBinding(
            cell_id="housing-e0-test-cell",
            case_id=case.case_id,
            case_sha256=case.artifact_sha256,
            world_seed=case.provenance.seed,
        ),
    )
    return case, state, plugin.phase_graph(case)


def _parse(
    plugin: HousingV1EnvironmentPlugin,
    case,
    state,
    phase,
    slot,
    payload: dict[str, object],
) -> ActionBundle:
    parsed = plugin.parse_action(
        case,
        state,
        phase,
        slot,
        CanonicalResponse(content=json.dumps(payload, sort_keys=True)),
    )
    assert parsed.status == "ok"
    assert parsed.bundle is not None
    return parsed.bundle


def test_housing_e0_happy_path_exercises_every_environment_hook() -> None:
    raw = _fixture()
    expected_hash = raw["artifact_sha256"]
    assert isinstance(expected_hash, str)
    assert (
        content_sha256({k: v for k, v in raw.items() if k != "artifact_sha256"})
        == expected_hash
    )

    plugin = HousingV1EnvironmentPlugin()
    assert isinstance(plugin, EnvironmentPlugin)
    case = plugin.validate_case(raw)
    state = plugin.initial_state(
        case,
        HousingV1CellBinding(
            cell_id="housing-e0-cell-1",
            case_id=CASE_ID,
            case_sha256=expected_hash,
            world_seed=7,
        ),
    )
    graph = plugin.phase_graph(case)
    assert graph.initial_phase_id == "contact"
    assert [phase.phase_id for phase in graph.phases] == [
        "contact",
        "respond",
        "commit",
    ]
    assert all(phase.mode == "simultaneous" for phase in graph.phases)

    contact = graph.phases[0]
    contact_slots = plugin.decision_slots(case, state, contact)
    assert [slot.order_key for slot in contact_slots] == [
        "tenant:00000000",
        "tenant:00000001",
    ]
    assert all(
        re.fullmatch(r"housing\.[0-9a-f]{64}\.tenant\.[0-9]+", slot.seat_id)
        for slot in contact_slots
    )
    assert all(case.artifact_sha256 in slot.seat_id for slot in contact_slots)
    assert all(case.artifact_sha256 in slot.slot_id for slot in contact_slots)
    assert all(CASE_ID not in slot.seat_id for slot in contact_slots)
    tenant_seats = {
        tenant_id: _slot_by_order_key(contact_slots, f"tenant:{tenant_id:08d}").seat_id
        for tenant_id in range(2)
    }
    reordered_state = dict(reversed(tuple(state.items())))
    assert content_sha256(reordered_state) == content_sha256(state)
    assert plugin.decision_slots(case, reordered_state, contact) == contact_slots
    before_contact_sha = content_sha256(state)
    contact_bundles = {}
    for tenant_id, rent in ((0, 1580.0), (1, 1570.0)):
        slot = _slot_by_seat(contact_slots, tenant_seats[tenant_id])
        assert len(slot.channels) == 2
        assert all(channel.min_actions == 0 for channel in slot.channels)
        assert all(channel.max_actions == 1 for channel in slot.channels)
        assert all(len(channel.recipient_seat_ids) == 1 for channel in slot.channels)
        observation = plugin.observe(case, state, contact, slot)
        assert plugin.observe(case, reordered_state, contact, slot) == observation
        assert observation.public_event_refs == ()
        assert observation.private_event_refs == ()
        assert observation.visible_payload["public_board"] == (
            {
                "listing_id": 0,
                "rent_asked": 2050.0,
                "beds": 1,
                "baths": 2,
                "minutes_to_campus": 8,
                "crime_index": 1.7,
                "minutes_to_groceries": 20,
                "orientation": "South",
                "status": "OPEN",
            },
            {
                "listing_id": 1,
                "rent_asked": 1660.0,
                "beds": 3,
                "baths": 1,
                "minutes_to_campus": 37,
                "crime_index": 2.9,
                "minutes_to_groceries": 5,
                "orientation": "South",
                "status": "OPEN",
            },
        )
        assert observation.visible_payload["remaining_rounds"] == 1
        assert observation.visible_payload["own_prior_offers"] == ()
        assert "private_cost" not in observation.visible_payload
        assert "projection" not in observation.visible_payload
        response = CanonicalResponse(
            content=json.dumps(
                {"kind": "offer", "listing_id": 1, "rent": rent},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        parsed = plugin.parse_action(
            case,
            state,
            contact,
            slot,
            response,
        )
        assert parsed.status == "ok"
        assert parsed.bundle is not None
        assert plugin.legal(case, state, contact, parsed.bundle).status == "legal"
        assert plugin.parse_action(case, state, contact, slot, response) == parsed
        contact_bundles[slot.slot_id] = parsed.bundle
    assert content_sha256(state) == before_contact_sha

    reversed_bundles = dict(
        zip(contact_bundles, reversed(tuple(contact_bundles.values())))
    )
    with pytest.raises(HousingAdapterContractError, match="mapping key"):
        plugin.step(case, state, contact, reversed_bundles)

    contacted = _step_with_mapping_order_proof(
        plugin, case, state, contact, contact_bundles
    )
    contacted_from_reordered_state = plugin.step(
        case,
        reordered_state,
        contact,
        contact_bundles,
    )
    assert content_sha256(state) == before_contact_sha
    assert contacted_from_reordered_state == contacted
    assert (
        contacted_from_reordered_state.model_dump_json() == contacted.model_dump_json()
    )
    assert content_sha256(contacted_from_reordered_state.state) == content_sha256(
        contacted.state
    )
    assert contacted_from_reordered_state.evidence == contacted.evidence
    assert contacted.next_phase_id == "respond"
    assert [offer["offer_id"] for offer in contacted.state["current_offers"]] == [
        "offer:r0:t0:l1",
        "offer:r0:t1:l1",
    ]

    respond_state = contacted.state
    respond = graph.phases[1]
    respond_slots = plugin.decision_slots(case, respond_state, respond)
    assert len(respond_slots) == 1
    landlord_slot = respond_slots[0]
    assert re.fullmatch(r"housing\.[0-9a-f]{64}\.landlord\.1", landlord_slot.seat_id)
    assert case.artifact_sha256 in landlord_slot.seat_id
    assert case.artifact_sha256 in landlord_slot.slot_id
    assert CASE_ID not in landlord_slot.seat_id
    assert [channel.channel_id for channel in landlord_slot.channels] == [
        "offer:r0:t0:l1",
        "offer:r0:t1:l1",
    ]
    landlord_observation = plugin.observe(case, respond_state, respond, landlord_slot)
    assert landlord_observation.public_event_refs == ()
    assert landlord_observation.private_event_refs == ()
    assert landlord_observation.visible_payload["public_board"] == (
        {
            "listing_id": 0,
            "rent_asked": 2050.0,
            "beds": 1,
            "baths": 2,
            "minutes_to_campus": 8,
            "crime_index": 1.7,
            "minutes_to_groceries": 20,
            "orientation": "South",
            "status": "OPEN",
        },
        {
            "listing_id": 1,
            "rent_asked": 1660.0,
            "beds": 3,
            "baths": 1,
            "minutes_to_campus": 37,
            "crime_index": 2.9,
            "minutes_to_groceries": 5,
            "orientation": "South",
            "status": "OPEN",
        },
    )
    assert landlord_observation.visible_payload["listing"]["listing_id"] == 1
    assert landlord_observation.visible_payload["private_cost"] == 1615.06
    assert "other_private_costs" not in landlord_observation.visible_payload
    assert 1994.28 not in landlord_observation.visible_payload.values()
    assert [
        offer["offer_id"] for offer in landlord_observation.visible_payload["inbox"]
    ] == [
        "offer:r0:t0:l1",
        "offer:r0:t1:l1",
    ]
    before_respond_sha = content_sha256(respond_state)
    malformed_response = plugin.parse_action(
        case,
        respond_state,
        respond,
        landlord_slot,
        CanonicalResponse(content="{}"),
    )
    assert malformed_response.status == "malformed"
    missing_response = plugin.step(case, respond_state, respond, {})
    assert missing_response.next_phase_id == "commit"
    assert missing_response.state["current_holds"] == ()
    assert missing_response.state["wasted_contacts"] == 2
    assert missing_response.evidence["native_verdicts"] == (
        {
            "actor_seat_id": landlord_slot.seat_id,
            "outcome": "pass",
            "reason": "missing_action",
            "reference_id": None,
        },
    )
    assert content_sha256(respond_state) == before_respond_sha

    parsed_response = plugin.parse_action(
        case,
        respond_state,
        respond,
        landlord_slot,
        CanonicalResponse(
            content=json.dumps(
                {
                    "kind": "respond",
                    "decisions": [
                        {
                            "offer_id": "offer:r0:t0:l1",
                            "decision": "accept",
                            "counter_rent": None,
                        },
                        {
                            "offer_id": "offer:r0:t1:l1",
                            "decision": "reject",
                            "counter_rent": None,
                        },
                    ],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        ),
    )
    assert parsed_response.status == "ok"
    assert parsed_response.bundle is not None
    assert len(parsed_response.bundle.actions) == 2
    assert (
        plugin.legal(case, respond_state, respond, parsed_response.bundle).status
        == "legal"
    )
    responded = plugin.step(
        case,
        respond_state,
        respond,
        {landlord_slot.slot_id: parsed_response.bundle},
    )
    assert content_sha256(respond_state) == before_respond_sha
    assert responded.next_phase_id == "commit"
    assert responded.state["current_holds"][0]["hold_id"] == "hold:r0:t0:l1"

    commit_state = responded.state
    commit = graph.phases[2]
    commit_slots = plugin.decision_slots(case, commit_state, commit)
    assert len(commit_slots) == 1
    commit_slot = commit_slots[0]
    commit_observation = plugin.observe(case, commit_state, commit, commit_slot)
    assert commit_observation.visible_payload["remaining_rounds"] == 1
    assert (
        commit_observation.visible_payload["own_prior_offers"][0]["offer_id"]
        == "offer:r0:t0:l1"
    )
    assert (
        commit_observation.visible_payload["active_hold"]["hold_id"] == "hold:r0:t0:l1"
    )
    parsed_commit = plugin.parse_action(
        case,
        commit_state,
        commit,
        commit_slot,
        CanonicalResponse(
            content='{"decision":"sign","hold_id":"hold:r0:t0:l1","kind":"commit"}'
        ),
    )
    assert parsed_commit.status == "ok"
    assert parsed_commit.bundle is not None
    assert (
        plugin.legal(case, commit_state, commit, parsed_commit.bundle).status == "legal"
    )
    committed = plugin.step(
        case,
        commit_state,
        commit,
        {commit_slot.slot_id: parsed_commit.bundle},
    )
    assert committed.next_phase_id is None
    terminal = plugin.terminal(case, committed.state)
    assert terminal is not None
    assert terminal.reason == "round_budget_exhausted"

    outcome = plugin.outcome(case, terminal)
    assert outcome.terminal_reason == "round_budget_exhausted"
    assert outcome.payload["assignment"] == ({"listing_id": 1, "tenant_id": 0},)
    assert outcome.payload["social_welfare"] == -50.28
    assert outcome.payload["ir_violations"] == (
        tenant_seats[0],
        landlord_slot.seat_id,
    )
    assert outcome.utility_by_seat[tenant_seats[0]] == -15.22
    assert outcome.utility_by_seat[landlord_slot.seat_id] == -35.06

    references = case.references
    assert references.lower.kind == "optimum_lower_bound"
    assert references.lower.proof_type == "constructive_no_trade_feasible_witness"
    assert references.lower.value == 0.0
    assert references.upper.kind == "optimum_upper_bound"
    assert references.upper.value == 334.35
    assert references.baseline.kind == "comparison_baseline"
    assert references.baseline.value == 64.79
    assert references.baseline.applicability == (
        "all-naive tenant population against fixed scripted landlords; same "
        "materialized case and round horizon"
    )
    assert references.baseline.provenance["tenant_population_assignment"] == (
        "all_tenants_naive"
    )
    assert outcome.payload["social_welfare"] < references.lower.value


def test_housing_e0_marks_formal_runner_and_measurement_routes_as_blocked() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case = plugin.validate_case(_fixture())

    contract = plugin.contract_status(case)

    assert contract.executable_scope == "environment_hook_expressibility_e0"
    assert contract.paper_primary_admission == "blocked"
    assert contract.unresolved_contract_gaps == (
        "official_observation_projection_authority",
        "formal_action_failure_disposition_requires_shared_contract",
        "timeout_to_native_consequence_requires_policy_pin",
        "formal_transition_authenticity_requires_event_chain",
        "formal_measurement_requires_task_1_1c",
        "run_global_action_identity_requires_task_2_1",
    )
    assert contract.state_validation_status == "structural_only"
    assert contract.identity_scope == "case_artifact_phase_round_slot_local"
    assert contract.exhausted_replayable_action_failure_policy == (
        "invalid_missing_or_timeout_record_typed_failure_then_phase_pass"
    )
    assert contract.invalid_measurement_policy == (
        "infrastructure_or_integration_failure_only_if_nonreplayable_or_terminal_score_unavailable"
    )
    assert {
        phase.invalid_action_policy for phase in plugin.phase_graph(case).phases
    } == {"formal_failure_disposition_requires_shared_contract"}
    assert not hasattr(plugin, "measurement_leaves")
    assert "outcome_support" not in case.references.model_dump(mode="python")


def test_housing_e0_rejects_structurally_invalid_respond_state() -> None:
    raw = _fixture()
    plugin = HousingV1EnvironmentPlugin()
    case = plugin.validate_case(raw)
    state = dict(
        plugin.initial_state(
            case,
            HousingV1CellBinding(
                cell_id="housing-e0-cell-malicious",
                case_id=CASE_ID,
                case_sha256=raw["artifact_sha256"],
                world_seed=7,
            ),
        )
    )
    state["phase"] = "respond"
    assert state["transition_index"] == 0
    assert state["current_offers"] == ()

    with pytest.raises(HousingAdapterContractError, match="structurally invalid state"):
        plugin.decision_slots(case, state, plugin.phase_graph(case).phases[1])


def test_housing_e0_registers_and_resolves_through_shared_registry() -> None:
    plugin = HousingV1EnvironmentPlugin()
    registry = PluginRegistry.from_objects(environments=[plugin])

    resolved = registry.resolve_environment(
        plugin.manifest.plugin_id,
        plugin.manifest.plugin_version,
    )

    assert resolved is plugin
    with pytest.raises(PluginVersionMismatch):
        registry.resolve_environment(plugin.manifest.plugin_id, "0.1.1")


@pytest.mark.parametrize("coercible_rounds", ["1", True])
def test_housing_case_rejects_coercible_round_budget_even_when_resealed(
    coercible_rounds: object,
) -> None:
    raw = _fixture()
    raw["rounds"] = coercible_rounds
    raw["artifact_sha256"] = content_sha256(
        {key: value for key, value in raw.items() if key != "artifact_sha256"}
    )

    with pytest.raises(ValidationError):
        HousingV1EnvironmentPlugin().validate_case(raw)


@pytest.mark.parametrize("invalid_rent", ["1.0", True, float("nan"), float("inf")])
def test_housing_records_reject_coercion_and_non_finite_numbers(
    invalid_rent: object,
) -> None:
    with pytest.raises(ValidationError):
        HousingRentRecord.model_validate({"tenant_id": 0, "rent": invalid_rent})


def test_housing_records_revalidate_unchecked_model_construct_payloads() -> None:
    unchecked = HousingRentRecord.model_construct(tenant_id="0", rent="1.0")
    unchecked_raw = unchecked.model_dump(mode="python", warnings=False)
    assert unchecked_raw == {
        "spec_version": "aeread.sdk_record/1",
        "tenant_id": "0",
        "rent": "1.0",
    }

    with pytest.raises(ValidationError):
        HousingRentRecord.model_validate(unchecked_raw)


@pytest.mark.parametrize(
    ("record_type", "payload"),
    [
        (HousingRentRecord, {"tenant_id": 0, "rent": -1.0}),
        (
            HousingOfferRecord,
            {
                "offer_id": "offer:r0:t0:l1",
                "tenant_id": 0,
                "listing_id": 1,
                "rent": -1.0,
                "round_index": 0,
            },
        ),
        (
            HousingHoldRecord,
            {
                "hold_id": "hold:r0:t0:l1",
                "tenant_id": 0,
                "listing_id": 1,
                "rent": -1.0,
                "round_index": 0,
            },
        ),
    ],
)
def test_housing_state_money_records_reject_negative_rent(
    record_type: type, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        record_type.model_validate(payload)


def test_housing_offer_history_rejects_two_offers_by_one_tenant_per_round() -> None:
    raw = _fixture()
    plugin = HousingV1EnvironmentPlugin()
    case = plugin.validate_case(raw)
    state = dict(
        plugin.initial_state(
            case,
            HousingV1CellBinding(
                cell_id="housing-e0-cell-history",
                case_id=CASE_ID,
                case_sha256=raw["artifact_sha256"],
                world_seed=7,
            ),
        )
    )
    state["offer_history"] = (
        {
            "offer_id": "offer:r0:t0:l0",
            "tenant_id": 0,
            "listing_id": 0,
            "rent": 1500.0,
            "round_index": 0,
        },
        {
            "offer_id": "offer:r0:t0:l1",
            "tenant_id": 0,
            "listing_id": 1,
            "rent": 1500.0,
            "round_index": 0,
        },
    )

    with pytest.raises(ValidationError, match="one offer per round"):
        HousingStateRecord.model_validate(state)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("cell_id", 1),
        ("case_id", b"case"),
        ("case_sha256", b"a" * 64),
        ("world_seed", "7"),
        ("world_seed", True),
    ],
)
def test_housing_cell_binding_rejects_id_and_integer_coercion(
    field_name: str, invalid_value: object
) -> None:
    payload: dict[str, object] = {
        "cell_id": "cell",
        "case_id": CASE_ID,
        "case_sha256": "a" * 64,
        "world_seed": 7,
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        HousingV1CellBinding.model_validate(payload)


def test_housing_seat_ids_survive_event_store_audience_roundtrip_without_privacy_leak(
    tmp_path: Path,
) -> None:
    raw = _fixture()
    malicious_case_id = "case:landlord:999/seat:public?\nraw"
    raw["case_id"] = malicious_case_id
    raw = _reseal(raw)
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin, raw)
    contact = graph.phases[0]
    contact_slots = plugin.decision_slots(case, state, contact)
    tenant_0 = _slot_by_order_key(contact_slots, "tenant:00000000")
    tenant_1 = _slot_by_order_key(contact_slots, "tenant:00000001")
    assert malicious_case_id not in tenant_0.seat_id
    assert re.fullmatch(r"housing\.[0-9a-f]{64}\.tenant\.0", tenant_0.seat_id)

    contact_bundles = {
        tenant_0.slot_id: _parse(
            plugin,
            case,
            state,
            contact,
            tenant_0,
            {"kind": "offer", "listing_id": 0, "rent": 2050.0},
        ),
        tenant_1.slot_id: _parse(
            plugin,
            case,
            state,
            contact,
            tenant_1,
            {"kind": "offer", "listing_id": 1, "rent": 1700.0},
        ),
    }
    case_local_ids = [
        *(slot.seat_id for slot in contact_slots),
        *(slot.slot_id for slot in contact_slots),
        *(
            recipient
            for slot in contact_slots
            for channel in slot.channels
            for recipient in channel.recipient_seat_ids
        ),
        *(
            action.action_id
            for bundle in contact_bundles.values()
            for action in bundle.actions
        ),
    ]
    assert all(case.artifact_sha256 in value for value in case_local_ids)

    tenant_observations = {
        slot.seat_id: plugin.observe(case, state, contact, slot)
        for slot in contact_slots
    }
    for tenant_id, slot in enumerate(contact_slots):
        observation = tenant_observations[slot.seat_id]
        _assert_role_payload_privacy(
            case, observation.visible_payload, "tenant", tenant_id
        )
        mutated = copy.deepcopy(_canonical_value(observation.visible_payload))
        mutated["public_board"][0]["renamed_shadow_metric"] = case.world.costs[0]
        with pytest.raises(AssertionError):
            _assert_role_payload_privacy(case, mutated, "tenant", tenant_id)

    contacted = plugin.step(case, state, contact, contact_bundles)
    respond = graph.phases[1]
    landlord_slots = plugin.decision_slots(case, contacted.state, respond)
    landlord_observations = {
        slot.seat_id: plugin.observe(case, contacted.state, respond, slot)
        for slot in landlord_slots
    }
    case_local_landlord_ids = [
        *(slot.seat_id for slot in landlord_slots),
        *(slot.slot_id for slot in landlord_slots),
    ]
    assert all(case.artifact_sha256 in value for value in case_local_landlord_ids)
    for listing_id, slot in enumerate(landlord_slots):
        observation = landlord_observations[slot.seat_id]
        _assert_role_payload_privacy(
            case, observation.visible_payload, "landlord", listing_id
        )
        assert (
            observation.visible_payload["public_board"]
            == next(iter(tenant_observations.values())).visible_payload["public_board"]
        )
        mutated = copy.deepcopy(_canonical_value(observation.visible_payload))
        mutated["public_board"][0]["renamed_shadow_metric"] = case.world.values[0][0]
        with pytest.raises(AssertionError):
            _assert_role_payload_privacy(case, mutated, "landlord", listing_id)

    identity = EventIdentity(
        run_plan_id="housing-plan",
        cell_id="housing-cell",
        episode_id="housing-episode",
        episode_attempt_id="housing-attempt",
    )
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=identity, trusted_root=tmp_path
    )
    store = EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, identity=identity
    )
    observations = {**tenant_observations, **landlord_observations}
    for seat_id, observation in observations.items():
        store.append(
            "observation_rendered",
            identity,
            f"seat:{seat_id}",
            {"observation": observation.visible_payload},
        )
    sealed = store.seal()
    for seat_id in observations:
        audience = f"seat:{seat_id}"
        view = store.project(sealed, audience)
        assert [event.payload_visible for event in view.events] == [
            event.visibility == audience for event in sealed.events
        ]
        assert sum(event.payload is not None for event in view.events) == 1


def test_contact_uses_one_directed_channel_per_listing_and_exactly_one_total_offer() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin)
    phase = graph.phases[0]
    slot = _slot_by_order_key(
        plugin.decision_slots(case, state, phase), "tenant:00000000"
    )

    assert [channel.channel_id for channel in slot.channels] == [
        "listing:0",
        "listing:1",
    ]
    assert all(channel.min_actions == 0 for channel in slot.channels)
    assert all(channel.max_actions == 1 for channel in slot.channels)
    assert all(len(channel.recipient_seat_ids) == 1 for channel in slot.channels)

    one_offer = _parse(
        plugin,
        case,
        state,
        phase,
        slot,
        {"kind": "offer", "listing_id": 1, "rent": 1700.0},
    )
    assert one_offer.actions[0].channel_id == "listing:1"
    assert plugin.legal(case, state, phase, one_offer).status == "legal"

    two_offers = ActionBundle(
        slot_id=slot.slot_id,
        actions=tuple(
            ActionEnvelope(
                action_id=f"action:{slot.slot_id}:listing:{listing_id}",
                slot_id=slot.slot_id,
                channel_id=f"listing:{listing_id}",
                actor_seat_id=slot.seat_id,
                sequence_index=listing_id,
                payload={
                    "kind": "offer",
                    "listing_id": listing_id,
                    "rent": 1700.0,
                },
            )
            for listing_id in range(2)
        ),
    )
    legality = plugin.legal(case, state, phase, two_offers)
    assert legality.status == "illegal"
    assert legality.reasons == ("contact_requires_exactly_one_offer",)


def test_missing_contact_is_native_pass_but_supplied_empty_bundle_is_illegal() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin)
    phase = graph.phases[0]
    slots = plugin.decision_slots(case, state, phase)
    first = _slot_by_order_key(slots, "tenant:00000000")
    second = _slot_by_order_key(slots, "tenant:00000001")
    first_offer = _parse(
        plugin,
        case,
        state,
        phase,
        first,
        {"kind": "offer", "listing_id": 0, "rent": 2050.0},
    )
    empty = ActionBundle(slot_id=second.slot_id, actions=())
    assert plugin.legal(case, state, phase, empty).status == "illegal"

    missing = plugin.step(case, state, phase, {first.slot_id: first_offer})
    assert [row["outcome"] for row in missing.evidence["native_verdicts"]] == [
        "applied",
        "pass",
    ]
    assert missing.evidence["native_verdicts"][1]["reason"] == "missing_action"

    before_sha = content_sha256(state)
    with pytest.raises(HousingAdapterContractError, match="illegal bundle"):
        plugin.step(
            case,
            state,
            phase,
            {first.slot_id: first_offer, second.slot_id: empty},
        )
    assert content_sha256(state) == before_sha


def test_respond_partial_and_omitted_decisions_follow_native_semantics() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin)
    contact = graph.phases[0]
    contact_slots = plugin.decision_slots(case, state, contact)
    bundles = {
        slot.slot_id: _parse(
            plugin,
            case,
            state,
            contact,
            slot,
            {
                "kind": "offer",
                "listing_id": 1,
                "rent": 1700.0 + index,
            },
        )
        for index, slot in enumerate(contact_slots)
    }
    contacted = plugin.step(case, state, contact, bundles)
    respond = graph.phases[1]
    slot = plugin.decision_slots(case, contacted.state, respond)[0]
    assert all(channel.min_actions == 0 for channel in slot.channels)
    assert [offer["offer_id"] for offer in contacted.state["current_offers"]] == [
        "offer:r0:t0:l1",
        "offer:r0:t1:l1",
    ]
    landlord_observation = plugin.observe(case, contacted.state, respond, slot)
    assert [
        offer["offer_id"] for offer in landlord_observation.visible_payload["inbox"]
    ] == ["offer:r0:t1:l1", "offer:r0:t0:l1"]

    partial = _parse(
        plugin,
        case,
        contacted.state,
        respond,
        slot,
        {
            "kind": "respond",
            "decisions": [
                {
                    "offer_id": "offer:r0:t1:l1",
                    "decision": "accept",
                    "counter_rent": None,
                }
            ],
        },
    )
    assert plugin.legal(case, contacted.state, respond, partial).status == "legal"
    partially_responded = plugin.step(
        case, contacted.state, respond, {slot.slot_id: partial}
    )
    assert partially_responded.state["current_holds"][0]["tenant_id"] == 1
    assert partially_responded.state["rejections"][0]["listing_ids"] == (1,)

    omitted = _parse(
        plugin,
        case,
        contacted.state,
        respond,
        slot,
        {"kind": "respond", "decisions": []},
    )
    assert omitted.actions == ()
    assert plugin.legal(case, contacted.state, respond, omitted).status == "legal"
    missing_result = plugin.step(case, contacted.state, respond, {})
    omitted_result = plugin.step(
        case, contacted.state, respond, {slot.slot_id: omitted}
    )
    assert omitted_result.state["current_holds"] == ()
    assert omitted_result.state == missing_result.state
    assert omitted_result.evidence["native_verdicts"][0]["outcome"] == "applied"
    assert omitted_result.evidence["native_verdicts"][0]["reason"] is None
    assert missing_result.evidence["native_verdicts"][0]["outcome"] == "pass"
    assert missing_result.evidence["native_verdicts"][0]["reason"] == "missing_action"
    assert omitted_result.evidence != missing_result.evidence


def test_negative_counter_is_rejected_before_step() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin)
    contact = graph.phases[0]
    tenant = _slot_by_order_key(
        plugin.decision_slots(case, state, contact), "tenant:00000000"
    )
    offer = _parse(
        plugin,
        case,
        state,
        contact,
        tenant,
        {"kind": "offer", "listing_id": 0, "rent": 100.0},
    )
    contacted = plugin.step(case, state, contact, {tenant.slot_id: offer})
    respond = graph.phases[1]
    landlord = plugin.decision_slots(case, contacted.state, respond)[0]
    negative = _parse(
        plugin,
        case,
        contacted.state,
        respond,
        landlord,
        {
            "kind": "respond",
            "decisions": [
                {
                    "offer_id": "offer:r0:t0:l0",
                    "decision": "counter",
                    "counter_rent": -1.0,
                }
            ],
        },
    )
    legality = plugin.legal(case, contacted.state, respond, negative)
    assert legality.status == "illegal"
    assert legality.reasons == ("invalid_counter_rent",)


def test_missing_commit_expires_hold_but_supplied_empty_bundle_is_illegal() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin, _rounds_case(2))
    contact = graph.phases[0]
    tenant = _slot_by_order_key(
        plugin.decision_slots(case, state, contact), "tenant:00000000"
    )
    offer = _parse(
        plugin,
        case,
        state,
        contact,
        tenant,
        {"kind": "offer", "listing_id": 1, "rent": 1700.0},
    )
    contacted = plugin.step(case, state, contact, {tenant.slot_id: offer})
    respond = graph.phases[1]
    landlord = plugin.decision_slots(case, contacted.state, respond)[0]
    response = _parse(
        plugin,
        case,
        contacted.state,
        respond,
        landlord,
        {
            "kind": "respond",
            "decisions": [
                {
                    "offer_id": "offer:r0:t0:l1",
                    "decision": "accept",
                    "counter_rent": None,
                }
            ],
        },
    )
    responded = plugin.step(
        case, contacted.state, respond, {landlord.slot_id: response}
    )
    commit = graph.phases[2]
    commit_slot = plugin.decision_slots(case, responded.state, commit)[0]
    empty = ActionBundle(slot_id=commit_slot.slot_id, actions=())
    assert plugin.legal(case, responded.state, commit, empty).status == "illegal"

    before_sha = content_sha256(responded.state)
    with pytest.raises(HousingAdapterContractError, match="illegal bundle"):
        plugin.step(case, responded.state, commit, {commit_slot.slot_id: empty})
    assert content_sha256(responded.state) == before_sha

    advanced = plugin.step(case, responded.state, commit, {})
    assert advanced.next_phase_id == "contact"
    assert advanced.state["round_index"] == 1
    assert advanced.state["pairs"] == ()
    assert advanced.state["rejections"][0]["listing_ids"] == (1,)
    assert advanced.evidence["native_verdicts"][0]["reason"] == "missing_action"


def test_two_round_walk_then_sign_preserves_history_rejection_and_remaining_rounds() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin, _rounds_case(2))
    contact, respond, commit = graph.phases
    tenant_0 = _slot_by_order_key(
        plugin.decision_slots(case, state, contact), "tenant:00000000"
    )
    first_offer = _parse(
        plugin,
        case,
        state,
        contact,
        tenant_0,
        {"kind": "offer", "listing_id": 1, "rent": 1700.0},
    )
    after_contact = plugin.step(case, state, contact, {tenant_0.slot_id: first_offer})
    landlord_1 = plugin.decision_slots(case, after_contact.state, respond)[0]
    first_response = _parse(
        plugin,
        case,
        after_contact.state,
        respond,
        landlord_1,
        {
            "kind": "respond",
            "decisions": [
                {
                    "offer_id": "offer:r0:t0:l1",
                    "decision": "accept",
                    "counter_rent": None,
                }
            ],
        },
    )
    after_respond = plugin.step(
        case, after_contact.state, respond, {landlord_1.slot_id: first_response}
    )
    first_commit_slot = plugin.decision_slots(case, after_respond.state, commit)[0]
    walk = _parse(
        plugin,
        case,
        after_respond.state,
        commit,
        first_commit_slot,
        {
            "kind": "commit",
            "decision": "walk",
            "hold_id": "hold:r0:t0:l1",
        },
    )
    round_one = plugin.step(
        case, after_respond.state, commit, {first_commit_slot.slot_id: walk}
    )

    tenant_0_round_one = _slot_by_order_key(
        plugin.decision_slots(case, round_one.state, contact), "tenant:00000000"
    )
    observation = plugin.observe(case, round_one.state, contact, tenant_0_round_one)
    assert observation.visible_payload["remaining_rounds"] == 1
    assert observation.visible_payload["rejected_listing_ids"] == (1,)
    assert [
        row["offer_id"] for row in observation.visible_payload["own_prior_offers"]
    ] == ["offer:r0:t0:l1"]
    assert "private_cost" not in _recursive_keys(observation.visible_payload)

    second_offer = _parse(
        plugin,
        case,
        round_one.state,
        contact,
        tenant_0_round_one,
        {"kind": "offer", "listing_id": 0, "rent": 2050.0},
    )
    round_one_contact = plugin.step(
        case, round_one.state, contact, {tenant_0_round_one.slot_id: second_offer}
    )
    landlord_0 = plugin.decision_slots(case, round_one_contact.state, respond)[0]
    second_response = _parse(
        plugin,
        case,
        round_one_contact.state,
        respond,
        landlord_0,
        {
            "kind": "respond",
            "decisions": [
                {
                    "offer_id": "offer:r1:t0:l0",
                    "decision": "accept",
                    "counter_rent": None,
                }
            ],
        },
    )
    round_one_respond = plugin.step(
        case,
        round_one_contact.state,
        respond,
        {landlord_0.slot_id: second_response},
    )
    second_commit_slot = plugin.decision_slots(case, round_one_respond.state, commit)[0]
    sign = _parse(
        plugin,
        case,
        round_one_respond.state,
        commit,
        second_commit_slot,
        {
            "kind": "commit",
            "decision": "sign",
            "hold_id": "hold:r1:t0:l0",
        },
    )
    finished = plugin.step(
        case,
        round_one_respond.state,
        commit,
        {second_commit_slot.slot_id: sign},
    )
    assert finished.next_phase_id is None
    assert finished.state["round_index"] == 2
    assert [row["offer_id"] for row in finished.state["offer_history"]] == [
        "offer:r0:t0:l1",
        "offer:r1:t0:l0",
    ]
    assert plugin.terminal(case, finished.state).reason == "round_budget_exhausted"


def test_market_can_terminate_early_when_all_listings_are_leased() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, state, graph = _case_and_state(plugin, _rounds_case(2))
    contact, respond, commit = graph.phases
    contact_slots = plugin.decision_slots(case, state, contact)
    contact_bundles = {}
    for tenant_id, listing_id in ((0, 0), (1, 1)):
        slot = _slot_by_order_key(contact_slots, f"tenant:{tenant_id:08d}")
        contact_bundles[slot.slot_id] = _parse(
            plugin,
            case,
            state,
            contact,
            slot,
            {"kind": "offer", "listing_id": listing_id, "rent": 2100.0},
        )
    contacted = _step_with_mapping_order_proof(
        plugin, case, state, contact, contact_bundles
    )
    response_bundles = {}
    for slot in plugin.decision_slots(case, contacted.state, respond):
        listing_id = int(slot.order_key.rsplit(":", 1)[1])
        offer_id = f"offer:r0:t{listing_id}:l{listing_id}"
        response_bundles[slot.slot_id] = _parse(
            plugin,
            case,
            contacted.state,
            respond,
            slot,
            {
                "kind": "respond",
                "decisions": [
                    {
                        "offer_id": offer_id,
                        "decision": "accept",
                        "counter_rent": None,
                    }
                ],
            },
        )
    responded = _step_with_mapping_order_proof(
        plugin, case, contacted.state, respond, response_bundles
    )
    commit_bundles = {}
    for slot in plugin.decision_slots(case, responded.state, commit):
        tenant_id = int(slot.order_key.rsplit(":", 1)[1])
        hold_id = f"hold:r0:t{tenant_id}:l{tenant_id}"
        commit_bundles[slot.slot_id] = _parse(
            plugin,
            case,
            responded.state,
            commit,
            slot,
            {"kind": "commit", "decision": "sign", "hold_id": hold_id},
        )
    finished = _step_with_mapping_order_proof(
        plugin, case, responded.state, commit, commit_bundles
    )
    assert finished.next_phase_id is None
    assert finished.state["round_index"] == 1
    terminal = plugin.terminal(case, finished.state)
    assert terminal is not None
    assert terminal.reason == "all_listings_leased"


def test_structural_terminal_without_transition_chain_is_not_formally_authentic() -> None:
    plugin = HousingV1EnvironmentPlugin()
    case, initial, _ = _case_and_state(plugin)
    forged = dict(initial)
    forged.update(
        {
            "phase": "finished",
            "pairs": (
                {"tenant_id": 0, "listing_id": 0},
                {"tenant_id": 1, "listing_id": 1},
            ),
            "signed_rents": (
                {"tenant_id": 0, "rent": 2050.0},
                {"tenant_id": 1, "rent": 1660.0},
            ),
        }
    )

    terminal = plugin.terminal(case, forged)
    assert terminal is not None
    assert terminal.reason == "all_listings_leased"
    assert plugin.contract_status(case).state_validation_status == "structural_only"
    assert (
        "formal_transition_authenticity_requires_event_chain"
        in plugin.contract_status(case).unresolved_contract_gaps
    )


@pytest.mark.parametrize(
    ("reference_name", "field_name", "tampered_value"),
    [
        ("lower", "objective_id", "other_objective"),
        ("lower", "opponent_condition", "candidate_only"),
        ("upper", "proof_type", "heuristic"),
        ("upper", "validity_domain", "other_domain"),
        ("baseline", "comparison_id", "other_policy"),
        ("baseline", "applicability", "any_legal_policy"),
    ],
)
def test_housing_reference_scope_and_provenance_are_exactly_pinned(
    reference_name: str, field_name: str, tampered_value: object
) -> None:
    raw = _fixture()
    references = raw["references"]
    assert isinstance(references, dict)
    reference = references[reference_name]
    assert isinstance(reference, dict)
    reference[field_name] = tampered_value
    _reseal(raw)

    with pytest.raises(ValidationError, match="reference"):
        HousingV1EnvironmentPlugin().validate_case(raw)
