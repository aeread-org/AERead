"""Immutable Housing E0 case/state records and native serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from aeread import housing_env as native
from aeread.sdk.v1 import (
    ComparisonBaselineReference,
    FrozenJSONDict,
    ImplementationRef,
    OptimizationBoundReference,
    StrictModel,
    content_sha256,
)
from aeread.sdk.v1.base import SDKFloat, SDKInt, SDKStr


_PR6_COMMIT = "793866b41b0c23a162b7d36d734087c0a4da16fd"
_NATIVE_SOURCE_SHA256 = (
    "096b9f8a33dab846f6b525b0af335e3200619806a2e5efeb507661a565552f6b"
)


class HousingAdapterContractError(ValueError):
    """The runner crossed a Housing adapter boundary inconsistently."""


class HousingListingRecord(StrictModel):
    listing_id: SDKInt = Field(ge=0)
    rent_asked: SDKInt = Field(ge=0)
    beds: SDKInt = Field(ge=0)
    baths: SDKInt = Field(ge=0)
    minutes_to_campus: SDKInt = Field(ge=0)
    crime_index: SDKFloat
    minutes_to_groceries: SDKInt = Field(ge=0)
    orientation: SDKStr


class HousingWorldRecord(StrictModel):
    world_kind: Literal["bid"]
    listings: tuple[HousingListingRecord, ...]
    values: tuple[tuple[SDKFloat, ...], ...]
    costs: tuple[SDKFloat, ...]
    ask: tuple[SDKFloat, ...]

    @model_validator(mode="after")
    def validate_shape(self) -> "HousingWorldRecord":
        listing_count = len(self.listings)
        if not self.values or not self.listings:
            raise ValueError("Housing E0 requires tenants and listings")
        if [listing.listing_id for listing in self.listings] != list(
            range(listing_count)
        ):
            raise ValueError("listing IDs must be contiguous and zero-based")
        if len(self.costs) != listing_count or len(self.ask) != listing_count:
            raise ValueError("cost and ask vectors must match the listing count")
        if any(len(row) != listing_count for row in self.values):
            raise ValueError("every tenant value row must match the listing count")
        if any(
            not math.isfinite(value)
            for value in (
                *self.costs,
                *self.ask,
                *(v for row in self.values for v in row),
            )
        ):
            raise ValueError("Housing world numbers must be finite")
        if any(
            float(listing.rent_asked) != self.ask[index]
            for index, listing in enumerate(self.listings)
        ):
            raise ValueError("public asks must match listing rent_asked")
        return self


class HousingProvenanceRecord(StrictModel):
    source_kind: Literal["generated"]
    generator_id: Literal["aeread.housing.make_bid_world"]
    generator_version: Literal["1.0.0"]
    generator_commit: Literal[_PR6_COMMIT]
    generator_source_sha256: Literal[_NATIVE_SOURCE_SHA256]
    seed: SDKInt = Field(ge=0)
    num_tenants: SDKInt = Field(ge=1)
    num_listings: SDKInt = Field(ge=1)
    common_weight: SDKFloat = Field(ge=0.0, le=1.0)
    materializer_id: Literal["housing-e0-static-materialization"]
    materializer_version: Literal["1.0.0"]


class HousingContractStatus(StrictModel):
    renderer_status: Literal["provisional_adapter_projection"]
    executable_scope: Literal["environment_hook_expressibility_e0"]
    state_validation_status: Literal["structural_only"]
    identity_scope: Literal["case_artifact_phase_round_slot_local"]
    exhausted_replayable_action_failure_policy: Literal[
        "invalid_missing_or_timeout_record_typed_failure_then_phase_pass"
    ]
    invalid_measurement_policy: Literal[
        "infrastructure_or_integration_failure_only_if_nonreplayable_or_terminal_score_unavailable"
    ]
    paper_primary_admission: Literal["blocked"]
    unresolved_contract_gaps: tuple[
        Literal[
            "official_observation_projection_authority",
            "formal_action_failure_disposition_requires_shared_contract",
            "timeout_to_native_consequence_requires_policy_pin",
            "formal_transition_authenticity_requires_event_chain",
            "formal_measurement_requires_task_1_1c",
            "run_global_action_identity_requires_task_2_1",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def require_known_gaps(self) -> "HousingContractStatus":
        expected = (
            "official_observation_projection_authority",
            "formal_action_failure_disposition_requires_shared_contract",
            "timeout_to_native_consequence_requires_policy_pin",
            "formal_transition_authenticity_requires_event_chain",
            "formal_measurement_requires_task_1_1c",
            "run_global_action_identity_requires_task_2_1",
        )
        if self.unresolved_contract_gaps != expected:
            raise ValueError("the Housing E0 formal blockers must remain explicit")
        return self


class HousingReferenceSet(StrictModel):
    lower: OptimizationBoundReference
    upper: OptimizationBoundReference
    baseline: ComparisonBaselineReference

    @model_validator(mode="after")
    def validate_reference_kinds(self) -> "HousingReferenceSet":
        if self.lower.kind != "optimum_lower_bound":
            raise ValueError("lower must be an optimum_lower_bound")
        if self.upper.kind != "optimum_upper_bound":
            raise ValueError("upper must be an optimum_upper_bound")
        if self.baseline.kind != "comparison_baseline":
            raise ValueError("baseline must remain a comparison baseline")
        if self.lower.proof_type != "constructive_no_trade_feasible_witness":
            raise ValueError("Housing lower bound must use the no-trade witness")
        return self


def _reference_implementation(implementation_id: str) -> ImplementationRef:
    return ImplementationRef(
        implementation_id=implementation_id,
        version="1.0.0",
        content_sha256=_NATIVE_SOURCE_SHA256,
    )


def _reference_horizon(rounds: int) -> str:
    return "one_round" if rounds == 1 else f"{rounds}_rounds"


def _expected_references(
    *, rounds: int, optimum: float, baseline: float
) -> HousingReferenceSet:
    common = {
        "objective_id": "housing_social_welfare",
        "objective_version": "1.0.0",
        "units": "utility",
        "direction": "maximize",
        "feasible_set": "housing_v1_all_legal_outcomes",
        "information_set": "full_materialized_world",
        "horizon": _reference_horizon(rounds),
        "opponent_condition": "any_legal_policy",
        "validity_domain": "materialized housing_v1 case",
    }
    return HousingReferenceSet(
        lower=OptimizationBoundReference(
            kind="optimum_lower_bound",
            value=0.0,
            proof_type="constructive_no_trade_feasible_witness",
            implementation=_reference_implementation("housing_no_trade_witness"),
            **common,
        ),
        upper=OptimizationBoundReference(
            kind="optimum_upper_bound",
            value=float(optimum),
            proof_type="exact_max_weight_assignment",
            implementation=_reference_implementation("housing_assignment_oracle"),
            **common,
        ),
        baseline=ComparisonBaselineReference(
            kind="comparison_baseline",
            value=float(baseline),
            comparison_id="housing_naive_scripted_market",
            comparison_version="1.0.0",
            units="utility",
            direction="maximize",
            provenance={
                "generator_commit": _PR6_COMMIT,
                "rounds": rounds,
                "strategy": "naive",
                "landlord_policy": "scripted",
                "tenant_policy": "naive",
                "tenant_population_assignment": "all_tenants_naive",
            },
            applicability=(
                "all-naive tenant population against fixed scripted landlords; same "
                "materialized case and round horizon"
            ),
            implementation=_reference_implementation(
                "housing_run_scripted_market_naive"
            ),
        ),
    )


class HousingV1CaseArtifact(StrictModel):
    spec_version: Literal["aeread.housing_case/0.1"]
    case_id: SDKStr
    family_id: Literal["housing_v1"]
    family_version: Literal["0.1.0-spike"]
    rounds: SDKInt = Field(ge=1)
    world: HousingWorldRecord
    provenance: HousingProvenanceRecord
    contract: HousingContractStatus
    references: HousingReferenceSet
    artifact_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="before")
    @classmethod
    def validate_raw_artifact_hash(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError("Housing case artifact must be an object")
        raw = dict(value)
        claimed = raw.pop("artifact_sha256", None)
        if type(claimed) is not str or content_sha256(raw) != claimed:
            raise ValueError("artifact_sha256 does not match canonical case content")
        return value

    @model_validator(mode="after")
    def validate_materialization(self) -> "HousingV1CaseArtifact":
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        provenance = self.provenance
        if provenance.num_tenants != len(
            self.world.values
        ) or provenance.num_listings != len(self.world.listings):
            raise ValueError("provenance dimensions must match the materialized world")

        source_path = Path(native.__file__)
        if (
            hashlib.sha256(source_path.read_bytes()).hexdigest()
            != _NATIVE_SOURCE_SHA256
        ):
            raise ValueError("native Housing source does not match the pinned artifact")

        regenerated = native.make_bid_world(
            provenance.num_tenants,
            provenance.num_listings,
            provenance.seed,
            provenance.common_weight,
        )
        if _world_record(regenerated) != self.world:
            raise ValueError("materialized world does not match the pinned generator")

        optimum = native.assignment_oracle(regenerated.surplus).total
        baseline = native.run_scripted_market(
            regenerated, rounds=self.rounds, strategy="naive"
        ).total
        expected_references = _expected_references(
            rounds=self.rounds,
            optimum=float(optimum),
            baseline=float(baseline),
        )
        if self.references != expected_references:
            raise ValueError(
                "Housing reference scope, provenance, implementation, or value "
                "does not match the pinned case contract"
            )
        return self


class HousingV1CellBinding(StrictModel):
    """Spike-local subset of PlanCell used to pin one direct hook execution."""

    cell_id: SDKStr
    case_id: SDKStr
    case_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    world_seed: SDKInt = Field(ge=0)


class HousingPairRecord(StrictModel):
    tenant_id: SDKInt = Field(ge=0)
    listing_id: SDKInt = Field(ge=0)


class HousingRentRecord(StrictModel):
    tenant_id: SDKInt = Field(ge=0)
    rent: SDKFloat = Field(ge=0.0)


class HousingOfferRecord(StrictModel):
    offer_id: SDKStr
    tenant_id: SDKInt = Field(ge=0)
    listing_id: SDKInt = Field(ge=0)
    rent: SDKFloat = Field(ge=0.0)
    round_index: SDKInt = Field(ge=0)


class HousingHoldRecord(StrictModel):
    hold_id: SDKStr
    tenant_id: SDKInt = Field(ge=0)
    listing_id: SDKInt = Field(ge=0)
    rent: SDKFloat = Field(ge=0.0)
    round_index: SDKInt = Field(ge=0)


class HousingRejectionRecord(StrictModel):
    tenant_id: SDKInt = Field(ge=0)
    listing_ids: tuple[SDKInt, ...]


class HousingStateRecord(StrictModel):
    spec_version: Literal["aeread.housing_state/0.1"] = "aeread.housing_state/0.1"
    case_id: SDKStr
    case_artifact_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    transition_index: SDKInt = Field(ge=0)
    phase: Literal["contact", "respond", "commit", "finished"]
    round_index: SDKInt = Field(ge=0)
    pairs: tuple[HousingPairRecord, ...] = ()
    signed_rents: tuple[HousingRentRecord, ...] = ()
    current_offers: tuple[HousingOfferRecord, ...] = ()
    current_holds: tuple[HousingHoldRecord, ...] = ()
    offer_history: tuple[HousingOfferRecord, ...] = ()
    rejections: tuple[HousingRejectionRecord, ...] = ()
    wasted_contacts: SDKInt = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_order_and_identity(self) -> "HousingStateRecord":
        for values, key, label in (
            (self.pairs, lambda value: value.tenant_id, "pair tenant"),
            (self.signed_rents, lambda value: value.tenant_id, "signed rent tenant"),
            (self.current_offers, lambda value: value.offer_id, "offer"),
            (self.current_holds, lambda value: value.hold_id, "hold"),
            (self.rejections, lambda value: value.tenant_id, "rejection tenant"),
        ):
            identities = [key(value) for value in values]
            if identities != sorted(identities) or len(identities) != len(
                set(identities)
            ):
                raise ValueError(f"{label} records must be unique and sorted")
        history_keys = [
            (offer.round_index, offer.tenant_id, offer.listing_id)
            for offer in self.offer_history
        ]
        if history_keys != sorted(history_keys) or len(history_keys) != len(
            set(history_keys)
        ):
            raise ValueError("offer history must be unique and sorted")
        tenant_rounds = [
            (offer.round_index, offer.tenant_id) for offer in self.offer_history
        ]
        if len(tenant_rounds) != len(set(tenant_rounds)):
            raise ValueError("each tenant may make at most one offer per round")
        return self


def _world_record(world: native.BidWorld) -> HousingWorldRecord:
    return HousingWorldRecord(
        world_kind="bid",
        listings=tuple(
            HousingListingRecord(
                listing_id=listing.listing_id,
                rent_asked=listing.rent_asked,
                beds=listing.beds,
                baths=listing.baths,
                minutes_to_campus=listing.minutes_to_campus,
                crime_index=listing.crime_index,
                minutes_to_groceries=listing.minutes_to_groceries,
                orientation=listing.orientation,
            )
            for listing in world.listings
        ),
        values=tuple(tuple(float(value) for value in row) for row in world.values),
        costs=tuple(float(value) for value in world.costs),
        ask=tuple(float(value) for value in world.ask),
    )


def _native_world(case: HousingV1CaseArtifact) -> native.BidWorld:
    return native.BidWorld(
        listings=[
            native.Listing(
                listing_id=listing.listing_id,
                rent_asked=listing.rent_asked,
                beds=listing.beds,
                baths=listing.baths,
                minutes_to_campus=listing.minutes_to_campus,
                crime_index=listing.crime_index,
                minutes_to_groceries=listing.minutes_to_groceries,
                orientation=listing.orientation,
            )
            for listing in case.world.listings
        ],
        values=[list(row) for row in case.world.values],
        costs=list(case.world.costs),
        ask=list(case.world.ask),
    )


def _offer_record(offer: native.Offer) -> HousingOfferRecord:
    return HousingOfferRecord(
        offer_id=offer.offer_id,
        tenant_id=offer.tenant_id,
        listing_id=offer.listing_id,
        rent=offer.rent,
        round_index=offer.round_index,
    )


def _hold_record(hold: native.Hold) -> HousingHoldRecord:
    return HousingHoldRecord(
        hold_id=hold.hold_id,
        tenant_id=hold.tenant_id,
        listing_id=hold.listing_id,
        rent=hold.rent,
        round_index=hold.round_index,
    )


def _native_offer(offer: HousingOfferRecord) -> native.Offer:
    return native.Offer(
        offer.offer_id,
        offer.tenant_id,
        offer.listing_id,
        offer.rent,
        offer.round_index,
    )


def _native_hold(hold: HousingHoldRecord) -> native.Hold:
    return native.Hold(
        hold.hold_id,
        hold.tenant_id,
        hold.listing_id,
        hold.rent,
        hold.round_index,
    )


def _tenant_seat(case: HousingV1CaseArtifact, tenant_id: int) -> str:
    return f"housing.{case.artifact_sha256}.tenant.{tenant_id}"


def _landlord_seat(case: HousingV1CaseArtifact, listing_id: int) -> str:
    return f"housing.{case.artifact_sha256}.landlord.{listing_id}"


def _tenant_id_for_seat(case: HousingV1CaseArtifact, seat_id: str) -> int:
    seats = {
        _tenant_seat(case, tenant_id): tenant_id
        for tenant_id in range(case.provenance.num_tenants)
    }
    try:
        return seats[seat_id]
    except KeyError as exc:
        raise HousingAdapterContractError(
            "seat is not a tenant in this case artifact"
        ) from exc


def _landlord_id_for_seat(case: HousingV1CaseArtifact, seat_id: str) -> int:
    seats = {
        _landlord_seat(case, listing_id): listing_id
        for listing_id in range(case.provenance.num_listings)
    }
    try:
        return seats[seat_id]
    except KeyError as exc:
        raise HousingAdapterContractError(
            "seat is not a landlord in this case artifact"
        ) from exc


def _slot_id(
    case: HousingV1CaseArtifact,
    state: HousingStateRecord,
    phase: str,
    role: str,
    actor_id: int,
) -> str:
    return (
        f"housing:{case.artifact_sha256}:r{state.round_index}:"
        f"{phase}:{role}:{actor_id}"
    )


def _state_json(state: HousingStateRecord) -> FrozenJSONDict:
    return FrozenJSONDict(state.model_dump(mode="python"))


def _reject_structurally_invalid_state(reason: str) -> None:
    raise HousingAdapterContractError(f"structurally invalid state: {reason}")


def _validate_structural_state(
    case: HousingV1CaseArtifact, state: HousingStateRecord
) -> None:
    tenant_ids = set(range(case.provenance.num_tenants))
    listing_ids = set(range(case.provenance.num_listings))
    if state.round_index > case.rounds:
        _reject_structurally_invalid_state("round_index exceeds the case horizon")

    phase_offset = {"contact": 0, "respond": 1, "commit": 2, "finished": 0}
    expected_transition_index = 3 * state.round_index + phase_offset[state.phase]
    if state.transition_index != expected_transition_index:
        _reject_structurally_invalid_state(
            "transition_index does not match round and phase"
        )

    pair_tenants = {pair.tenant_id for pair in state.pairs}
    pair_listings = {pair.listing_id for pair in state.pairs}
    if any(
        pair.tenant_id not in tenant_ids or pair.listing_id not in listing_ids
        for pair in state.pairs
    ):
        _reject_structurally_invalid_state(
            "pair identity is outside the materialized world"
        )
    if len(pair_tenants) != len(state.pairs) or len(pair_listings) != len(state.pairs):
        _reject_structurally_invalid_state(
            "pair tenants and listings must each be unique"
        )
    if {rent.tenant_id for rent in state.signed_rents} != pair_tenants:
        _reject_structurally_invalid_state(
            "signed-rent tenants must exactly match pairs"
        )

    rejection_tenants = {row.tenant_id for row in state.rejections}
    if rejection_tenants != tenant_ids:
        _reject_structurally_invalid_state("rejection records must cover every tenant")
    for rejection in state.rejections:
        if tuple(sorted(set(rejection.listing_ids))) != rejection.listing_ids or any(
            listing_id not in listing_ids for listing_id in rejection.listing_ids
        ):
            _reject_structurally_invalid_state(
                "rejected listing identities must be unique, sorted, and in range"
            )

    def validate_offer(offer: HousingOfferRecord) -> None:
        if offer.tenant_id not in tenant_ids or offer.listing_id not in listing_ids:
            _reject_structurally_invalid_state(
                "offer identity is outside the materialized world"
            )
        if offer.round_index >= case.rounds:
            _reject_structurally_invalid_state(
                "offer round is outside the case horizon"
            )
        if offer.offer_id != (
            f"offer:r{offer.round_index}:t{offer.tenant_id}:l{offer.listing_id}"
        ):
            _reject_structurally_invalid_state("offer_id is not canonical")

    for offer in (*state.offer_history, *state.current_offers):
        validate_offer(offer)
    if any(offer.round_index > state.round_index for offer in state.offer_history):
        _reject_structurally_invalid_state("offer history contains a future round")

    history_current_round = {
        offer.offer_id: offer
        for offer in state.offer_history
        if offer.round_index == state.round_index
    }
    current_offers = {offer.offer_id: offer for offer in state.current_offers}
    if state.phase in {"contact", "finished"}:
        if state.current_offers or state.current_holds:
            _reject_structurally_invalid_state(
                "contact and finished phases cannot retain offers or holds"
            )
        if history_current_round:
            _reject_structurally_invalid_state(
                "contact and finished phases cannot have current-round offer history"
            )
    else:
        if current_offers != history_current_round:
            _reject_structurally_invalid_state(
                "current offers must match current-round offer history"
            )
        unmatched_tenants = tenant_ids - pair_tenants
        open_listings = listing_ids - pair_listings
        offer_tenants = [offer.tenant_id for offer in state.current_offers]
        if not set(offer_tenants).issubset(unmatched_tenants) or len(
            offer_tenants
        ) != len(set(offer_tenants)):
            _reject_structurally_invalid_state(
                "respond and commit allow at most one offer per unmatched tenant"
            )
        if any(offer.listing_id not in open_listings for offer in state.current_offers):
            _reject_structurally_invalid_state(
                "current offer targets an unavailable listing"
            )
        if state.phase == "respond" and state.current_holds:
            _reject_structurally_invalid_state("respond phase cannot contain holds")

    hold_tenants: set[int] = set()
    hold_listings: set[int] = set()
    current_offer_pairs = {
        (offer.tenant_id, offer.listing_id) for offer in state.current_offers
    }
    for hold in state.current_holds:
        if hold.tenant_id not in tenant_ids or hold.listing_id not in listing_ids:
            _reject_structurally_invalid_state(
                "hold identity is outside the materialized world"
            )
        if hold.round_index != state.round_index or hold.hold_id != (
            f"hold:r{hold.round_index}:t{hold.tenant_id}:l{hold.listing_id}"
        ):
            _reject_structurally_invalid_state("hold round or hold_id is not canonical")
        if hold.tenant_id in pair_tenants or hold.listing_id in pair_listings:
            _reject_structurally_invalid_state(
                "hold references an unavailable participant"
            )
        if (hold.tenant_id, hold.listing_id) not in current_offer_pairs:
            _reject_structurally_invalid_state("hold is not backed by a current offer")
        if hold.tenant_id in hold_tenants or hold.listing_id in hold_listings:
            _reject_structurally_invalid_state("holds must be one-to-one")
        hold_tenants.add(hold.tenant_id)
        hold_listings.add(hold.listing_id)

    market = _hydrate_market(case, state)
    if (state.phase == "finished") != market.finished:
        _reject_structurally_invalid_state(
            "finished phase disagrees with native terminal state"
        )


def _state_record(
    case: HousingV1CaseArtifact, state: Mapping[str, object]
) -> HousingStateRecord:
    parsed = HousingStateRecord.model_validate(state)
    if (
        parsed.case_id != case.case_id
        or parsed.case_artifact_sha256 != case.artifact_sha256
    ):
        raise HousingAdapterContractError("state is not bound to this case artifact")
    _validate_structural_state(case, parsed)
    return parsed


def _hydrate_market(
    case: HousingV1CaseArtifact, state: HousingStateRecord
) -> native.HousingMarket:
    market = native.HousingMarket(_native_world(case), rounds=case.rounds)
    market.round_index = state.round_index
    market.pairs = [(pair.tenant_id, pair.listing_id) for pair in state.pairs]
    market.signed_rent = {row.tenant_id: row.rent for row in state.signed_rents}
    market._taken = {pair.listing_id for pair in state.pairs}
    market._matched = {pair.tenant_id for pair in state.pairs}
    offers: dict[int, list[native.Offer]] = {}
    for offer in state.current_offers:
        offers.setdefault(offer.listing_id, []).append(_native_offer(offer))
    market._offers = {
        listing_id: tuple(
            sorted(
                listing_offers,
                key=lambda offer: (-offer.rent, offer.tenant_id),
            )
        )
        for listing_id, listing_offers in sorted(offers.items())
    }
    market._holds = {hold.tenant_id: _native_hold(hold) for hold in state.current_holds}
    market.rejected = {row.tenant_id: set(row.listing_ids) for row in state.rejections}
    market.wasted_contacts = state.wasted_contacts
    market.phase = state.phase
    return market


def _capture_state(
    case: HousingV1CaseArtifact,
    market: native.HousingMarket,
    *,
    transition_index: int,
    offer_history: Sequence[HousingOfferRecord],
) -> HousingStateRecord:
    current_offers = tuple(
        sorted(
            (
                _offer_record(offer)
                for offers in market._offers.values()
                for offer in offers
            ),
            key=lambda offer: offer.offer_id,
        )
    )
    return HousingStateRecord(
        case_id=case.case_id,
        case_artifact_sha256=case.artifact_sha256,
        transition_index=transition_index,
        phase=market.phase,
        round_index=market.round_index,
        pairs=tuple(
            HousingPairRecord(tenant_id=tenant_id, listing_id=listing_id)
            for tenant_id, listing_id in sorted(market.pairs)
        ),
        signed_rents=tuple(
            HousingRentRecord(tenant_id=tenant_id, rent=rent)
            for tenant_id, rent in sorted(market.signed_rent.items())
        ),
        current_offers=current_offers,
        current_holds=tuple(
            sorted(
                (_hold_record(hold) for hold in market._holds.values()),
                key=lambda hold: hold.hold_id,
            )
        ),
        offer_history=tuple(
            sorted(
                offer_history,
                key=lambda offer: (
                    offer.round_index,
                    offer.tenant_id,
                    offer.listing_id,
                ),
            )
        ),
        rejections=tuple(
            HousingRejectionRecord(
                tenant_id=tenant_id,
                listing_ids=tuple(sorted(listing_ids)),
            )
            for tenant_id, listing_ids in sorted(market.rejected.items())
        ),
        wasted_contacts=market.wasted_contacts,
    )
