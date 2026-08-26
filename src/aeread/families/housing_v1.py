"""Provider-free Housing environment-hook E0 over Chenyu's native market.

This direct-hook adapter proves that the family contract can express native phases,
observations, explicit absences, transitions, and outcomes. It is not a formal
measurement admission: shared action-failure disposition, transition-chain evidence,
and an executable verifier remain outside this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math

from aeread import housing_env as native
from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    ActionEnvelope,
    CanonicalResponse,
    DecisionSlot,
    FamilyOutcome,
    FrozenJSONDict,
    LegalityResult,
    ObservationEnvelope,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    TerminalResult,
    TransitionResult,
    content_sha256,
    validate_action_bundle,
)
from aeread.sdk.v1.errors import BundleValidationError

from .housing_v1_records import (
    _capture_state,
    _hold_record,
    _hydrate_market,
    _landlord_id_for_seat,
    _landlord_seat,
    _native_world,
    _offer_record,
    _slot_id,
    _state_json,
    _state_record,
    _tenant_id_for_seat,
    _tenant_seat,
    HousingAdapterContractError,
    HousingContractStatus,
    HousingOfferRecord,
    HousingRentRecord,
    HousingStateRecord,
    HousingV1CaseArtifact,
    HousingV1CellBinding,
)


def _parse_json_object(response: CanonicalResponse) -> dict[str, object]:
    if response.content is None or response.tool_calls:
        raise ValueError("Housing E0 requires one JSON content response")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    parsed = json.loads(response.content, object_pairs_hook=reject_duplicate_keys)
    if type(parsed) is not dict:
        raise ValueError("Housing response must be a JSON object")
    return parsed


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


class HousingV1EnvironmentPlugin:
    """Provisional direct-hook adapter for one provider-free Housing E0 path."""

    manifest = PluginManifest(
        plugin_id="aeread.housing_v1.e0_spike",
        plugin_version="0.1.0",
        sdk_api="aeread.sdk/v1",
    )

    def validate_case(self, payload: Mapping[str, object]) -> HousingV1CaseArtifact:
        return HousingV1CaseArtifact.model_validate(payload)

    def initial_state(
        self, case: HousingV1CaseArtifact, cell: HousingV1CellBinding
    ) -> FrozenJSONDict:
        if (
            cell.case_id != case.case_id
            or cell.case_sha256 != case.artifact_sha256
            or cell.world_seed != case.provenance.seed
        ):
            raise HousingAdapterContractError(
                "cell identity, case hash, and world seed must match the artifact"
            )
        market = native.HousingMarket(_native_world(case), rounds=case.rounds)
        state = _capture_state(case, market, transition_index=0, offer_history=())
        return _state_json(state)

    def phase_graph(self, case: HousingV1CaseArtifact) -> PhaseGraph:
        tenant_actions = max(1, case.provenance.num_tenants)
        landlord_actions = max(1, case.provenance.num_listings)
        # The case owner ruled on this in PR #6 (2026-08-23): after the runner's
        # declared retry policy is exhausted, record the typed action failure and
        # pass for that phase — an invalid contact makes no offer, an invalid
        # response makes no hold, an invalid commit lets the hold expire — and do
        # not invalidate the episode. The runner now rejects any other value, so
        # the earlier placeholder would stop every housing episode.
        formal_failure_blocker = "pass"
        return PhaseGraph(
            initial_phase_id="contact",
            phases=(
                PhaseSpec(
                    phase_id="contact",
                    actor_selector="unmatched_tenant_seats",
                    mode="simultaneous",
                    observation_schema_by_role={
                        "tenant": "aeread.housing.tenant_observation/0.1"
                    },
                    action_schema_by_role={
                        "tenant": "aeread.housing.contact_action/0.1"
                    },
                    max_logical_actions=tenant_actions,
                    invalid_action_policy=formal_failure_blocker,
                    next_phases=("respond",),
                ),
                PhaseSpec(
                    phase_id="respond",
                    actor_selector="landlord_seats_with_inbox",
                    mode="simultaneous",
                    observation_schema_by_role={
                        "landlord": "aeread.housing.landlord_observation/0.1"
                    },
                    action_schema_by_role={
                        "landlord": "aeread.housing.respond_action/0.1"
                    },
                    max_logical_actions=landlord_actions,
                    invalid_action_policy=formal_failure_blocker,
                    next_phases=("commit",),
                ),
                PhaseSpec(
                    phase_id="commit",
                    actor_selector="tenant_seats_with_hold",
                    mode="simultaneous",
                    observation_schema_by_role={
                        "tenant": "aeread.housing.tenant_observation/0.1"
                    },
                    action_schema_by_role={
                        "tenant": "aeread.housing.commit_action/0.1"
                    },
                    max_logical_actions=tenant_actions,
                    invalid_action_policy=formal_failure_blocker,
                    next_phases=("contact",),
                ),
            ),
        )

    def _require_phase(
        self,
        case: HousingV1CaseArtifact,
        state: HousingStateRecord,
        phase: PhaseSpec,
    ) -> None:
        expected = {item.phase_id: item for item in self.phase_graph(case).phases}.get(
            state.phase
        )
        if expected is None or phase != expected:
            raise HousingAdapterContractError(
                f"phase {phase.phase_id!r} does not match state {state.phase!r}"
            )

    def decision_slots(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
    ) -> Sequence[DecisionSlot]:
        parsed = _state_record(case, state)
        self._require_phase(case, parsed, phase)
        market = _hydrate_market(case, parsed)
        slots: list[DecisionSlot] = []
        if phase.phase_id == "contact":
            for tenant_id in market.unmatched_tenants():
                slot_id = _slot_id(case, parsed, "contact", "tenant", tenant_id)
                slots.append(
                    DecisionSlot(
                        slot_id=slot_id,
                        seat_id=_tenant_seat(case, tenant_id),
                        channels=tuple(
                            ActionChannel(
                                channel_id=f"listing:{listing_id}",
                                recipient_seat_ids=(_landlord_seat(case, listing_id),),
                                action_schema_ref="aeread.housing.offer/0.1",
                                min_actions=0,
                                max_actions=1,
                            )
                            for listing_id in market.open_listings()
                        ),
                        observation_schema_ref="aeread.housing.tenant_observation/0.1",
                        response_schema_ref="aeread.housing.contact_response/0.1",
                        order_key=f"tenant:{tenant_id:08d}",
                    )
                )
        elif phase.phase_id == "respond":
            offers_by_listing: dict[int, list[HousingOfferRecord]] = {}
            for offer in parsed.current_offers:
                offers_by_listing.setdefault(offer.listing_id, []).append(offer)
            for listing_id, offers in sorted(offers_by_listing.items()):
                slot_id = _slot_id(case, parsed, "respond", "landlord", listing_id)
                slots.append(
                    DecisionSlot(
                        slot_id=slot_id,
                        seat_id=_landlord_seat(case, listing_id),
                        channels=tuple(
                            ActionChannel(
                                channel_id=offer.offer_id,
                                recipient_seat_ids=(
                                    _tenant_seat(case, offer.tenant_id),
                                ),
                                action_schema_ref="aeread.housing.response_decision/0.1",
                                min_actions=0,
                                max_actions=1,
                            )
                            for offer in sorted(
                                offers, key=lambda value: value.offer_id
                            )
                        ),
                        observation_schema_ref="aeread.housing.landlord_observation/0.1",
                        response_schema_ref="aeread.housing.respond_response/0.1",
                        order_key=f"landlord:{listing_id:08d}",
                    )
                )
        elif phase.phase_id == "commit":
            for hold in parsed.current_holds:
                slot_id = _slot_id(case, parsed, "commit", "tenant", hold.tenant_id)
                slots.append(
                    DecisionSlot(
                        slot_id=slot_id,
                        seat_id=_tenant_seat(case, hold.tenant_id),
                        channels=(
                            ActionChannel(
                                channel_id=hold.hold_id,
                                recipient_seat_ids=(
                                    _landlord_seat(case, hold.listing_id),
                                ),
                                action_schema_ref="aeread.housing.commit/0.1",
                                min_actions=1,
                                max_actions=1,
                            ),
                        ),
                        observation_schema_ref="aeread.housing.tenant_observation/0.1",
                        response_schema_ref="aeread.housing.commit_response/0.1",
                        order_key=f"tenant:{hold.tenant_id:08d}",
                    )
                )
        return tuple(slots)

    def _require_slot(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> None:
        declared = {
            item.slot_id: item for item in self.decision_slots(case, state, phase)
        }
        if declared.get(slot.slot_id) != slot:
            raise HousingAdapterContractError("slot is not declared by this state")

    def observe(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope:
        self._require_slot(case, state, phase, slot)
        parsed = _state_record(case, state)
        market = _hydrate_market(case, parsed)
        public_board = market.board()
        remaining_rounds = max(case.rounds - parsed.round_index, 0)
        if phase.phase_id == "respond":
            listing_id = _landlord_id_for_seat(case, slot.seat_id)
            own_listing = next(
                row for row in public_board if row["listing_id"] == listing_id
            )
            inbox = tuple(
                offer.model_dump(mode="python")
                for offer in sorted(
                    (
                        offer
                        for offer in parsed.current_offers
                        if offer.listing_id == listing_id
                    ),
                    key=lambda offer: (-offer.rent, offer.tenant_id),
                )
            )
            payload = {
                "role": "landlord",
                "seat_id": slot.seat_id,
                "listing_id": listing_id,
                "round_index": parsed.round_index,
                "remaining_rounds": remaining_rounds,
                "phase": phase.phase_id,
                "public_board": public_board,
                "listing": own_listing,
                "private_cost": case.world.costs[listing_id],
                "inbox": inbox,
            }
        else:
            tenant_id = _tenant_id_for_seat(case, slot.seat_id)
            active_hold = next(
                (
                    hold.model_dump(mode="python")
                    for hold in parsed.current_holds
                    if hold.tenant_id == tenant_id
                ),
                None,
            )
            prior_offers = [
                offer.model_dump(mode="python")
                for offer in parsed.offer_history
                if offer.tenant_id == tenant_id
            ]
            rejected = next(
                row.listing_ids
                for row in parsed.rejections
                if row.tenant_id == tenant_id
            )
            payload = {
                "role": "tenant",
                "seat_id": slot.seat_id,
                "tenant_id": tenant_id,
                "round_index": parsed.round_index,
                "remaining_rounds": remaining_rounds,
                "phase": phase.phase_id,
                "public_board": public_board,
                "rejected_listing_ids": rejected,
                "active_hold": active_hold,
                "own_prior_offers": prior_offers,
                "private_values": case.world.values[tenant_id],
            }
        return ObservationEnvelope(
            schema_ref=slot.observation_schema_ref,
            slot_id=slot.slot_id,
            visible_payload=payload,
            public_event_refs=(),
            # Direct-hook E0 has no EventStore yet; never fabricate trace references.
            private_event_refs=(),
        )

    def parse_action(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult:
        self._require_slot(case, state, phase, slot)
        try:
            raw = _parse_json_object(response)
            if phase.phase_id == "contact":
                if set(raw) != {"kind", "listing_id", "rent"}:
                    raise ValueError("contact response fields are not exact")
                if raw["kind"] != "offer" or type(raw["listing_id"]) is not int:
                    raise ValueError("contact response requires an integer listing ID")
                if not _finite_number(raw["rent"]):
                    raise ValueError("contact rent must be finite")
                actions = (
                    ActionEnvelope(
                        action_id=f"action:{slot.slot_id}:offer",
                        slot_id=slot.slot_id,
                        channel_id=f"listing:{raw['listing_id']}",
                        actor_seat_id=slot.seat_id,
                        sequence_index=0,
                        payload={
                            "kind": "offer",
                            "listing_id": raw["listing_id"],
                            "rent": float(raw["rent"]),
                        },
                    ),
                )
            elif phase.phase_id == "respond":
                if set(raw) != {"kind", "decisions"} or raw["kind"] != "respond":
                    raise ValueError("respond response fields are not exact")
                decisions = raw["decisions"]
                if type(decisions) is not list:
                    raise ValueError("decisions must be a JSON array")
                by_offer: dict[str, dict[str, object]] = {}
                for decision in decisions:
                    if type(decision) is not dict or set(decision) != {
                        "offer_id",
                        "decision",
                        "counter_rent",
                    }:
                        raise ValueError("response decision fields are not exact")
                    offer_id = decision["offer_id"]
                    choice = decision["decision"]
                    counter = decision["counter_rent"]
                    if type(offer_id) is not str or offer_id in by_offer:
                        raise ValueError("offer IDs must be strings and unique")
                    if choice not in {"accept", "counter", "reject"}:
                        raise ValueError("unknown landlord decision")
                    if choice == "counter":
                        if not _finite_number(counter):
                            raise ValueError("counter requires a finite rent")
                        counter = float(counter)
                    elif counter is not None:
                        raise ValueError("accept/reject counter_rent must be null")
                    by_offer[offer_id] = {
                        "kind": "response_decision",
                        "offer_id": offer_id,
                        "decision": choice,
                        "counter_rent": counter,
                    }
                actions = tuple(
                    ActionEnvelope(
                        action_id=f"action:{slot.slot_id}:{offer_id}",
                        slot_id=slot.slot_id,
                        channel_id=offer_id,
                        actor_seat_id=slot.seat_id,
                        sequence_index=index,
                        payload=by_offer[offer_id],
                    )
                    for index, offer_id in enumerate(sorted(by_offer))
                )
            else:
                if set(raw) != {"kind", "decision", "hold_id"}:
                    raise ValueError("commit response fields are not exact")
                if (
                    raw["kind"] != "commit"
                    or raw["decision"] not in {"sign", "walk"}
                    or type(raw["hold_id"]) is not str
                ):
                    raise ValueError("commit response is malformed")
                hold_id = raw["hold_id"]
                actions = (
                    ActionEnvelope(
                        action_id=f"action:{slot.slot_id}:{hold_id}",
                        slot_id=slot.slot_id,
                        channel_id=hold_id,
                        actor_seat_id=slot.seat_id,
                        sequence_index=0,
                        payload={
                            "kind": "commit",
                            "decision": raw["decision"],
                            "hold_id": hold_id,
                        },
                    ),
                )
            return ParseResult(
                status="ok", bundle=ActionBundle(slot_id=slot.slot_id, actions=actions)
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return ParseResult(
                status="malformed",
                error_code="housing_response_malformed",
                message=str(exc),
            )

    def legal(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult:
        parsed = _state_record(case, state)
        self._require_phase(case, parsed, phase)
        slots = {slot.slot_id: slot for slot in self.decision_slots(case, state, phase)}
        slot = slots.get(bundle.slot_id)
        if slot is None:
            return LegalityResult(status="illegal", reasons=("unknown_slot",))
        try:
            validate_action_bundle(bundle, slot)
        except BundleValidationError as exc:
            return LegalityResult(status="illegal", reasons=(str(exc),))

        market = _hydrate_market(case, parsed)
        if phase.phase_id == "contact":
            if len(bundle.actions) != 1:
                return LegalityResult(
                    status="illegal",
                    reasons=("contact_requires_exactly_one_offer",),
                )
            action = bundle.actions[0]
            if set(action.payload) != {"kind", "listing_id", "rent"} or (
                action.payload.get("kind") != "offer"
            ):
                return LegalityResult(
                    status="illegal", reasons=("invalid_contact_payload",)
                )
            listing_id = action.payload.get("listing_id")
            rent = action.payload.get("rent")
            if type(listing_id) is not int or listing_id not in market.open_listings():
                return LegalityResult(status="illegal", reasons=("listing_not_open",))
            if action.channel_id != f"listing:{listing_id}":
                return LegalityResult(
                    status="illegal", reasons=("listing_channel_mismatch",)
                )
            if not _finite_number(rent) or float(rent) < 0.0:
                return LegalityResult(status="illegal", reasons=("invalid_rent",))
        elif phase.phase_id == "respond":
            offers = {offer.offer_id: offer for offer in parsed.current_offers}
            binding_count = 0
            for action in bundle.actions:
                if (
                    set(action.payload)
                    != {
                        "kind",
                        "offer_id",
                        "decision",
                        "counter_rent",
                    }
                    or action.payload.get("kind") != "response_decision"
                ):
                    return LegalityResult(
                        status="illegal", reasons=("invalid_response_payload",)
                    )
                offer_id = action.payload.get("offer_id")
                if offer_id not in offers or action.channel_id != offer_id:
                    return LegalityResult(status="illegal", reasons=("unknown_offer",))
                decision = action.payload.get("decision")
                counter = action.payload.get("counter_rent")
                if decision not in {"accept", "counter", "reject"}:
                    return LegalityResult(
                        status="illegal", reasons=("invalid_response_decision",)
                    )
                if decision == "counter":
                    if not _finite_number(counter) or float(counter) < 0.0:
                        return LegalityResult(
                            status="illegal", reasons=("invalid_counter_rent",)
                        )
                elif counter is not None:
                    return LegalityResult(
                        status="illegal", reasons=("invalid_counter_rent",)
                    )
                if decision in {"accept", "counter"}:
                    binding_count += 1
            if binding_count > 1:
                return LegalityResult(
                    status="illegal", reasons=("hold_capacity_exceeded",)
                )
        else:
            action = bundle.actions[0]
            holds = {hold.hold_id: hold for hold in parsed.current_holds}
            if set(action.payload) != {"kind", "decision", "hold_id"} or (
                action.payload.get("kind") != "commit"
                or action.payload.get("decision") not in {"sign", "walk"}
                or type(action.payload.get("hold_id")) is not str
            ):
                return LegalityResult(
                    status="illegal", reasons=("invalid_commit_payload",)
                )
            hold_id = action.payload.get("hold_id")
            if hold_id not in holds or action.channel_id != hold_id:
                return LegalityResult(status="illegal", reasons=("unknown_hold",))
        return LegalityResult(status="legal")

    def step(
        self,
        case: HousingV1CaseArtifact,
        state: Mapping[str, object],
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],
    ) -> TransitionResult:
        parsed = _state_record(case, state)
        self._require_phase(case, parsed, phase)
        slots = self.decision_slots(case, state, phase)
        expected = {slot.slot_id for slot in slots}
        if any(key != bundle.slot_id for key, bundle in bundles.items()):
            raise HousingAdapterContractError(
                "bundle mapping key must match the bundle slot_id"
            )
        submitted = set(bundles)
        if submitted - expected:
            raise HousingAdapterContractError(
                "step received a bundle for an undeclared decision slot"
            )
        for slot in slots:
            bundle = bundles.get(slot.slot_id)
            if bundle is None:
                continue
            result = self.legal(case, state, phase, bundle)
            if result.status != "legal":
                raise HousingAdapterContractError(
                    f"step received illegal bundle: {result.reasons!r}"
                )

        market = _hydrate_market(case, parsed)
        if phase.phase_id == "contact":
            native_actions: dict[int, tuple[int, float]] = {}
            for slot in slots:
                bundle = bundles.get(slot.slot_id)
                if bundle is None:
                    continue
                action = bundle.actions[0]
                tenant_id = _tenant_id_for_seat(case, slot.seat_id)
                native_actions[tenant_id] = (
                    int(action.payload["listing_id"]),
                    float(action.payload["rent"]),
                )
            phase_result = market.submit_offers(native_actions)
            new_offers = tuple(
                sorted(
                    (
                        _offer_record(offer)
                        for values in phase_result.inbox.values()
                        for offer in values
                    ),
                    key=lambda offer: (
                        offer.round_index,
                        offer.tenant_id,
                        offer.listing_id,
                    ),
                )
            )
            offer_history = (*parsed.offer_history, *new_offers)
        elif phase.phase_id == "respond":
            by_id = {offer.offer_id: offer for offer in parsed.current_offers}
            native_responses: dict[int, dict[int, tuple[str, float | None]]] = {}
            for slot in slots:
                bundle = bundles.get(slot.slot_id)
                if bundle is None:
                    continue
                listing_id = _landlord_id_for_seat(case, slot.seat_id)
                decisions: dict[int, tuple[str, float | None]] = {}
                for action in bundle.actions:
                    offer = by_id[str(action.payload["offer_id"])]
                    decisions[offer.tenant_id] = (
                        str(action.payload["decision"]),
                        (
                            None
                            if action.payload["counter_rent"] is None
                            else float(action.payload["counter_rent"])
                        ),
                    )
                native_responses[listing_id] = decisions
            phase_result = market.submit_responses(native_responses)
            offer_history = parsed.offer_history
        else:
            native_commits: dict[int, tuple[str, str]] = {}
            for slot in slots:
                bundle = bundles.get(slot.slot_id)
                if bundle is None:
                    continue
                action = bundle.actions[0]
                tenant_id = _tenant_id_for_seat(case, slot.seat_id)
                native_commits[tenant_id] = (
                    str(action.payload["decision"]),
                    str(action.payload["hold_id"]),
                )
            phase_result = market.submit_commits(native_commits)
            offer_history = parsed.offer_history

        next_state = _capture_state(
            case,
            market,
            transition_index=parsed.transition_index + 1,
            offer_history=offer_history,
        )
        actor_role = "landlord" if phase.phase_id == "respond" else "tenant"
        evidence = {
            "phase": phase.phase_id,
            "native_verdicts": [
                {
                    "actor_seat_id": (
                        _landlord_seat(case, actor_id)
                        if actor_role == "landlord"
                        else _tenant_seat(case, actor_id)
                    ),
                    "outcome": verdict.outcome,
                    "reason": verdict.reason,
                    "reference_id": verdict.reference_id,
                }
                for actor_id, verdict in sorted(phase_result.verdicts.items())
            ],
            "next_state_sha256": content_sha256(next_state),
        }
        return TransitionResult(
            state=next_state.model_dump(mode="python"),
            next_phase_id=None if market.finished else market.phase,
            evidence=evidence,
        )

    def terminal(
        self, case: HousingV1CaseArtifact, state: Mapping[str, object]
    ) -> TerminalResult | None:
        parsed = _state_record(case, state)
        market = _hydrate_market(case, parsed)
        if not market.finished:
            return None
        if not market.open_listings():
            reason = "all_listings_leased"
        elif not market.unmatched_tenants():
            reason = "all_tenants_matched"
        else:
            reason = "round_budget_exhausted"
        return TerminalResult(
            status="terminal",
            reason=reason,
            final_state=parsed.model_dump(mode="python"),
        )

    def outcome(
        self, case: HousingV1CaseArtifact, terminal: TerminalResult
    ) -> FamilyOutcome:
        parsed = _state_record(case, terminal.final_state)
        expected = self.terminal(case, terminal.final_state)
        if expected is None or expected.reason != terminal.reason:
            raise HousingAdapterContractError(
                "terminal result does not match final state"
            )
        economics = _hydrate_market(case, parsed).economics()
        utility_by_seat = {
            **{
                _tenant_seat(case, tenant_id): payoff
                for tenant_id, payoff in sorted(economics.tenant_payoffs.items())
            },
            **{
                _landlord_seat(case, listing_id): payoff
                for listing_id, payoff in sorted(economics.landlord_payoffs.items())
            },
        }
        violations = tuple(
            (
                _tenant_seat(case, int(value.split(":", 1)[1]))
                if value.startswith("tenant:")
                else _landlord_seat(case, int(value.split(":", 1)[1]))
            )
            for value in economics.ir_violations
        )
        return FamilyOutcome(
            terminal_reason=terminal.reason,
            payload={
                "assignment": [
                    {"tenant_id": tenant_id, "listing_id": listing_id}
                    for tenant_id, listing_id in economics.assignment.pairs
                ],
                "signed_rents": [
                    {"tenant_seat_id": _tenant_seat(case, tenant_id), "rent": rent}
                    for tenant_id, rent in sorted(economics.signed_rents.items())
                ],
                "tenant_payoffs": [
                    {"seat_id": _tenant_seat(case, tenant_id), "utility": payoff}
                    for tenant_id, payoff in sorted(economics.tenant_payoffs.items())
                ],
                "landlord_payoffs": [
                    {
                        "seat_id": _landlord_seat(case, listing_id),
                        "utility": payoff,
                    }
                    for listing_id, payoff in sorted(economics.landlord_payoffs.items())
                ],
                "social_welfare": economics.social_welfare,
                "ir_violations": violations,
                "unhoused": economics.assignment.unhoused,
            },
            utility_by_seat=utility_by_seat,
        )

    def contract_status(self, case: HousingV1CaseArtifact) -> HousingContractStatus:
        return case.contract


plugin = HousingV1EnvironmentPlugin()


__all__ = [
    "HousingAdapterContractError",
    "HousingContractStatus",
    "HousingRentRecord",
    "HousingV1CaseArtifact",
    "HousingV1CellBinding",
    "HousingV1EnvironmentPlugin",
    "plugin",
]
