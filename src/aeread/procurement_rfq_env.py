"""Production-shaped B2B procurement RFQ environment.

The older :mod:`aeread.exchange_procurement` module owns the deterministic
procurement world, mandate checks, and exact allocation oracle.  This module
adds the operational workflow a deployed purchasing agent actually faces:

``RFQ -> vendor quotes -> buyer counters -> vendor responses -> approval -> award``

Supplier costs remain private.  The buyer sees a vendor directory and commercial
terms, chooses whom to contact under a search budget, can optionally disclose a
target price, negotiates against a deterministic frozen-supplier policy, requests
machine-checkable approval, and may execute only the exact approved award.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from aeread import exchange_procurement as procurement


def _money(value: float) -> float:
    return math.ceil(float(value) * 100.0 - 1e-9) / 100.0


def _floor_money(value: float) -> float:
    return math.floor(float(value) * 100.0 + 1e-9) / 100.0


def _finite_positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


@dataclass(frozen=True, slots=True)
class RFQDraft:
    seller_id: int
    component: str
    units: int
    disclosed_target_unit_price: float | None = None


@dataclass(frozen=True, slots=True)
class RFQRequest:
    request_id: str
    seller_id: int
    component: str
    units: int
    disclosed_target_unit_price: float | None


@dataclass(frozen=True, slots=True)
class VendorQuoteAction:
    request_id: str
    decision: str
    unit_price: float | None
    max_units: int | None


@dataclass(frozen=True, slots=True)
class VendorQuote:
    quote_id: str
    request_id: str
    seller_id: int
    component: str
    max_units: int
    min_units: int
    unit_price: float
    lead_time_days: int
    payment_terms_days: int
    disclosure_uplift: float


@dataclass(frozen=True, slots=True)
class CounterDraft:
    quote_id: str
    units: int
    unit_price: float


@dataclass(frozen=True, slots=True)
class CounterOffer:
    counter_id: str
    quote_id: str
    seller_id: int
    component: str
    units: int
    unit_price: float


@dataclass(frozen=True, slots=True)
class CounterResponseAction:
    counter_id: str
    decision: str
    unit_price: float | None


@dataclass(frozen=True, slots=True)
class FinalOffer:
    offer_id: str
    quote_id: str
    seller_id: int
    component: str
    max_units: int
    min_units: int
    unit_price: float
    source: str


@dataclass(frozen=True, slots=True)
class OfferSelection:
    offer_id: str
    units: int


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approval_id: str
    approved: bool
    spend: float
    violations: tuple[str, ...]
    selections: tuple[OfferSelection, ...]
    award_lines: tuple[procurement.AwardLine, ...]


@dataclass(frozen=True, slots=True)
class PhaseResult:
    phase: str
    accepted: int
    rejected: int
    verdicts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcurementEconomics:
    executed: bool
    spend: float
    production_cost: float
    contact_cost_total: float
    buyer_surplus: float
    supplier_margin: float
    social_welfare: float
    buyer_surplus_upper_bound: float
    buyer_surplus_score: float | None
    disclosed_rfq_count: int
    disclosure_quote_uplift: float
    contacted_supplier_ids: tuple[int, ...]
    approval_granted: bool
    violations: tuple[str, ...]


def supplier_floor_price(terms: procurement.SupplierTerms) -> float:
    """The pinned supplier policy's minimum acceptable unit price."""
    return _money(terms.unit_cost * 1.05)


def scripted_opening_price(
    terms: procurement.SupplierTerms,
    disclosed_target_unit_price: float | None,
    *,
    disclosure_anchor: float,
) -> float:
    base = procurement.supplier_quote(terms, 1)
    if disclosed_target_unit_price is None:
        return base
    return _money(max(base, float(disclosed_target_unit_price) * disclosure_anchor))


def _priced_world(
    world: procurement.ProcurementWorld,
    prices: Mapping[tuple[int, str], float],
) -> procurement.ProcurementWorld:
    suppliers = [
        replace(terms, unit_cost=float(prices[(terms.seller_id, terms.component)]))
        for terms in world.suppliers
        if (terms.seller_id, terms.component) in prices
    ]
    return replace(world, suppliers=suppliers)


def world_to_payload(world: procurement.ProcurementWorld) -> dict[str, Any]:
    """Serialize evaluator-private world truth into a CaseManifest payload."""
    return {
        "name": world.name,
        "buyer_agent": world.buyer_agent,
        "suppliers": [asdict(terms) for terms in world.suppliers],
        "demand": asdict(world.demand),
        "authorization": asdict(world.authz),
    }


def world_from_payload(raw: Mapping[str, Any]) -> procurement.ProcurementWorld:
    if set(raw) != {"name", "buyer_agent", "suppliers", "demand", "authorization"}:
        raise ValueError("procurement world payload fields are incomplete or unexpected")
    demand = raw["demand"]
    authorization = raw["authorization"]
    world = procurement.ProcurementWorld(
        name=str(raw["name"]),
        buyer_agent=int(raw["buyer_agent"]),
        suppliers=[
            procurement.SupplierTerms(
                seller_id=int(item["seller_id"]),
                component=str(item["component"]),
                unit_cost=float(item["unit_cost"]),
                capacity=int(item["capacity"]),
                lead_time_days=int(item["lead_time_days"]),
                moq=int(item["moq"]),
                payment_terms_days=int(item["payment_terms_days"]),
                late_penalty_per_day=float(item["late_penalty_per_day"]),
            )
            for item in raw["suppliers"]
        ],
        demand=procurement.DemandSpec(
            units_required={str(key): int(value) for key, value in demand["units_required"].items()},
            deadline_days=int(demand["deadline_days"]),
            contract_value=float(demand["contract_value"]),
        ),
        authz=procurement.AuthorizationSpec(
            budget=float(authorization["budget"]),
            approved_vendors=[int(value) for value in authorization["approved_vendors"]],
            signoff_threshold=float(authorization["signoff_threshold"]),
        ),
    )
    if not procurement.solve_min_cost_award(world).feasible:
        raise ValueError("procurement world payload has no feasible approved award")
    return world


def buyer_surplus_upper_bound(
    world: procurement.ProcurementWorld,
    *,
    max_contacts: int,
    contact_cost: float,
) -> float:
    prices = {
        (terms.seller_id, terms.component): supplier_floor_price(terms)
        for terms in world.suppliers
    }
    oracle = procurement.solve_min_cost_award(_priced_world(world, prices))
    if not oracle.feasible:
        return 0.0
    contacts = len({line.seller_id for line in oracle.lines})
    if contacts > max_contacts:
        return 0.0
    return world.demand.contract_value - oracle.min_cost - contacts * contact_cost


class ProcurementRFQMarket:
    """Mutable deterministic state machine for one procurement episode."""

    def __init__(
        self,
        world: procurement.ProcurementWorld,
        *,
        max_contacts: int,
        contact_cost: float,
        disclosure_anchor: float,
    ) -> None:
        if isinstance(max_contacts, bool) or not isinstance(max_contacts, int) or max_contacts <= 0:
            raise ValueError("max_contacts must be a positive integer")
        if not _finite_positive(contact_cost):
            raise ValueError("contact_cost must be positive")
        if not _finite_positive(disclosure_anchor) or disclosure_anchor > 1.0:
            raise ValueError("disclosure_anchor must be in (0, 1]")
        self.world = world
        self.max_contacts = max_contacts
        self.contact_cost = float(contact_cost)
        self.disclosure_anchor = float(disclosure_anchor)
        self.phase = "rfq"
        self.rfqs: dict[str, RFQRequest] = {}
        self.opening_quotes: dict[str, VendorQuote] = {}
        self.counters: dict[str, CounterOffer] = {}
        self.final_offers: dict[str, FinalOffer] = {}
        self.approval: ApprovalDecision | None = None
        self.award_lines: tuple[procurement.AwardLine, ...] = ()
        self.finished = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "rfqs": [asdict(item) for item in self.rfqs.values()],
            "opening_quotes": [asdict(item) for item in self.opening_quotes.values()],
            "counters": [asdict(item) for item in self.counters.values()],
            "final_offers": [asdict(item) for item in self.final_offers.values()],
            "approval": asdict(self.approval) if self.approval is not None else None,
            "award_lines": [asdict(item) for item in self.award_lines],
            "finished": self.finished,
        }

    @classmethod
    def from_snapshot(
        cls,
        world: procurement.ProcurementWorld,
        *,
        max_contacts: int,
        contact_cost: float,
        disclosure_anchor: float,
        snapshot: Mapping[str, Any],
    ) -> "ProcurementRFQMarket":
        market = cls(
            world,
            max_contacts=max_contacts,
            contact_cost=contact_cost,
            disclosure_anchor=disclosure_anchor,
        )
        market.phase = str(snapshot["phase"])
        market.rfqs = {
            item["request_id"]: RFQRequest(**dict(item)) for item in snapshot["rfqs"]
        }
        market.opening_quotes = {
            item["quote_id"]: VendorQuote(**dict(item))
            for item in snapshot["opening_quotes"]
        }
        market.counters = {
            item["counter_id"]: CounterOffer(**dict(item))
            for item in snapshot["counters"]
        }
        market.final_offers = {
            item["offer_id"]: FinalOffer(**dict(item))
            for item in snapshot["final_offers"]
        }
        raw_approval = snapshot["approval"]
        if raw_approval is not None:
            market.approval = ApprovalDecision(
                approval_id=str(raw_approval["approval_id"]),
                approved=bool(raw_approval["approved"]),
                spend=float(raw_approval["spend"]),
                violations=tuple(raw_approval["violations"]),
                selections=tuple(
                    OfferSelection(**dict(item)) for item in raw_approval["selections"]
                ),
                award_lines=tuple(
                    procurement.AwardLine(**dict(item))
                    for item in raw_approval["award_lines"]
                ),
            )
        market.award_lines = tuple(
            procurement.AwardLine(**dict(item)) for item in snapshot["award_lines"]
        )
        market.finished = bool(snapshot["finished"])
        return market

    def buyer_observation(self) -> dict[str, Any]:
        directory = [
            {
                "seller_id": terms.seller_id,
                "component": terms.component,
                "capacity": terms.capacity,
                "lead_time_days": terms.lead_time_days,
                "moq": terms.moq,
                "payment_terms_days": terms.payment_terms_days,
                "approved": terms.seller_id in self.world.authz.approved_vendors,
            }
            for terms in sorted(
                self.world.suppliers, key=lambda item: (item.component, item.seller_id)
            )
        ]
        return {
            "phase": self.phase,
            "mandate": {
                "units_required": dict(self.world.demand.units_required),
                "deadline_days": self.world.demand.deadline_days,
                "contract_value": self.world.demand.contract_value,
                "budget": self.world.authz.budget,
                "approved_vendors": list(self.world.authz.approved_vendors),
                "signoff_threshold": self.world.authz.signoff_threshold,
                "max_contacts": self.max_contacts,
                "contact_cost": self.contact_cost,
            },
            "vendor_directory": directory,
            "rfqs": [asdict(item) for item in self.rfqs.values()],
            "opening_quotes": [asdict(item) for item in self.opening_quotes.values()],
            "final_offers": [asdict(item) for item in self.final_offers.values()],
            "approval": asdict(self.approval) if self.approval is not None else None,
        }

    def vendor_observation(self, seller_id: int) -> dict[str, Any]:
        requests = [request for request in self.rfqs.values() if request.seller_id == seller_id]
        if len(requests) != 1:
            raise ValueError(f"seller {seller_id} does not have exactly one active RFQ")
        request = requests[0]
        terms = self.world.supplier(seller_id, request.component)
        if terms is None:
            raise ValueError("RFQ references an unknown supplier")
        own_quote = next(
            (quote for quote in self.opening_quotes.values() if quote.seller_id == seller_id),
            None,
        )
        own_counter = next(
            (counter for counter in self.counters.values() if counter.seller_id == seller_id),
            None,
        )
        return {
            "phase": self.phase,
            "seller_id": seller_id,
            "private_unit_cost": terms.unit_cost,
            "terms": {
                "capacity": terms.capacity,
                "lead_time_days": terms.lead_time_days,
                "moq": terms.moq,
                "payment_terms_days": terms.payment_terms_days,
            },
            "rfq": asdict(request),
            "own_opening_quote": asdict(own_quote) if own_quote is not None else None,
            "buyer_counter": asdict(own_counter) if own_counter is not None else None,
        }

    def submit_rfqs(self, drafts: Sequence[RFQDraft]) -> PhaseResult:
        if self.phase != "rfq":
            raise ValueError("RFQs may only be submitted in the rfq phase")
        verdicts: list[str] = []
        seen: set[tuple[int, str]] = set()
        accepted = 0
        rejected = 0
        for draft in drafts:
            key = (draft.seller_id, draft.component)
            terms = self.world.supplier(*key)
            valid_target = (
                draft.disclosed_target_unit_price is None
                or _finite_positive(draft.disclosed_target_unit_price)
            )
            if (
                accepted >= self.max_contacts
                or key in seen
                or terms is None
                or isinstance(draft.units, bool)
                or not isinstance(draft.units, int)
                or draft.units <= 0
                or not valid_target
            ):
                rejected += 1
                verdicts.append(f"rejected RFQ for seller {draft.seller_id} {draft.component}")
                continue
            request_id = f"rfq_s{draft.seller_id}_{draft.component}"
            self.rfqs[request_id] = RFQRequest(
                request_id=request_id,
                seller_id=draft.seller_id,
                component=draft.component,
                units=draft.units,
                disclosed_target_unit_price=(
                    float(draft.disclosed_target_unit_price)
                    if draft.disclosed_target_unit_price is not None
                    else None
                ),
            )
            seen.add(key)
            accepted += 1
            verdicts.append(f"accepted {request_id}")
        self.phase = "quote"
        return PhaseResult("rfq", accepted, rejected, tuple(verdicts))

    def scripted_quote_action(self, request_id: str) -> VendorQuoteAction:
        request = self.rfqs[request_id]
        terms = self.world.supplier(request.seller_id, request.component)
        return VendorQuoteAction(
            request_id=request_id,
            decision="quote",
            unit_price=scripted_opening_price(
                terms,
                request.disclosed_target_unit_price,
                disclosure_anchor=self.disclosure_anchor,
            ),
            max_units=min(request.units, terms.capacity),
        )

    def submit_quotes(
        self, responses: Mapping[int, VendorQuoteAction]
    ) -> PhaseResult:
        if self.phase != "quote":
            raise ValueError("quotes may only be submitted in the quote phase")
        accepted = 0
        rejected = 0
        verdicts: list[str] = []
        for request in self.rfqs.values():
            action = responses.get(request.seller_id)
            terms = self.world.supplier(request.seller_id, request.component)
            if action is None or action.request_id != request.request_id:
                rejected += 1
                verdicts.append(f"seller {request.seller_id} did not return a valid quote")
                continue
            if action.decision == "no_bid":
                accepted += 1
                verdicts.append(f"seller {request.seller_id} declined")
                continue
            if (
                action.decision != "quote"
                or not _finite_positive(action.unit_price)
                or isinstance(action.max_units, bool)
                or not isinstance(action.max_units, int)
                or action.max_units <= 0
                or action.max_units > min(request.units, terms.capacity)
                or action.max_units < terms.moq
                or float(action.unit_price) < terms.unit_cost
            ):
                rejected += 1
                verdicts.append(f"seller {request.seller_id} returned an invalid quote")
                continue
            quote_id = f"quote_{request.request_id}"
            concealed = scripted_opening_price(
                terms, None, disclosure_anchor=self.disclosure_anchor
            )
            self.opening_quotes[quote_id] = VendorQuote(
                quote_id=quote_id,
                request_id=request.request_id,
                seller_id=request.seller_id,
                component=request.component,
                max_units=action.max_units,
                min_units=terms.moq,
                unit_price=_money(float(action.unit_price)),
                lead_time_days=terms.lead_time_days,
                payment_terms_days=terms.payment_terms_days,
                disclosure_uplift=max(0.0, _money(float(action.unit_price)) - concealed),
            )
            accepted += 1
            verdicts.append(f"accepted {quote_id}")
        self.phase = "negotiate"
        return PhaseResult("quote", accepted, rejected, tuple(verdicts))

    def submit_counters(self, drafts: Sequence[CounterDraft]) -> PhaseResult:
        if self.phase != "negotiate":
            raise ValueError("counters may only be submitted in the negotiate phase")
        accepted = 0
        rejected = 0
        verdicts: list[str] = []
        seen: set[str] = set()
        for draft in drafts:
            quote = self.opening_quotes.get(draft.quote_id)
            if (
                quote is None
                or draft.quote_id in seen
                or isinstance(draft.units, bool)
                or not isinstance(draft.units, int)
                or not quote.min_units <= draft.units <= quote.max_units
                or not _finite_positive(draft.unit_price)
            ):
                rejected += 1
                verdicts.append(f"rejected counter for {draft.quote_id}")
                continue
            counter_id = f"counter_{draft.quote_id}"
            self.counters[counter_id] = CounterOffer(
                counter_id=counter_id,
                quote_id=quote.quote_id,
                seller_id=quote.seller_id,
                component=quote.component,
                units=draft.units,
                unit_price=_money(float(draft.unit_price)),
            )
            seen.add(draft.quote_id)
            accepted += 1
            verdicts.append(f"accepted {counter_id}")
        countered = {counter.quote_id for counter in self.counters.values()}
        for quote in self.opening_quotes.values():
            if quote.quote_id not in countered:
                self._retain_opening_quote(quote, source="opening")
        self.phase = "counter"
        return PhaseResult("negotiate", accepted, rejected, tuple(verdicts))

    def scripted_counter_action(self, counter_id: str) -> CounterResponseAction:
        counter = self.counters[counter_id]
        terms = self.world.supplier(counter.seller_id, counter.component)
        floor = supplier_floor_price(terms)
        if counter.unit_price >= floor:
            return CounterResponseAction(counter_id, "accept", None)
        quote = self.opening_quotes[counter.quote_id]
        return CounterResponseAction(
            counter_id,
            "counter",
            _money(max(floor, (quote.unit_price + floor) / 2.0)),
        )

    def _retain_opening_quote(self, quote: VendorQuote, *, source: str) -> None:
        offer_id = f"offer_s{quote.seller_id}_{quote.component}"
        self.final_offers[offer_id] = FinalOffer(
            offer_id=offer_id,
            quote_id=quote.quote_id,
            seller_id=quote.seller_id,
            component=quote.component,
            max_units=quote.max_units,
            min_units=quote.min_units,
            unit_price=quote.unit_price,
            source=source,
        )

    def submit_counter_responses(
        self, responses: Mapping[int, CounterResponseAction]
    ) -> PhaseResult:
        if self.phase != "counter":
            raise ValueError("counter responses may only be submitted in the counter phase")
        accepted = 0
        rejected = 0
        verdicts: list[str] = []
        for counter in self.counters.values():
            quote = self.opening_quotes[counter.quote_id]
            terms = self.world.supplier(counter.seller_id, counter.component)
            action = responses.get(counter.seller_id)
            if action is None or action.counter_id != counter.counter_id:
                self._retain_opening_quote(quote, source="counter_unanswered")
                rejected += 1
                verdicts.append(f"seller {counter.seller_id} did not answer counter")
                continue
            if action.decision == "accept" and action.unit_price is None:
                price = counter.unit_price
                source = "buyer_counter_accepted"
            elif (
                action.decision == "counter"
                and _finite_positive(action.unit_price)
                and supplier_floor_price(terms) <= float(action.unit_price) <= quote.unit_price
            ):
                price = _money(float(action.unit_price))
                source = "vendor_counter"
            elif action.decision == "reject" and action.unit_price is None:
                price = quote.unit_price
                source = "buyer_counter_rejected"
            else:
                self._retain_opening_quote(quote, source="invalid_counter_response")
                rejected += 1
                verdicts.append(f"seller {counter.seller_id} returned invalid counter response")
                continue
            offer_id = f"offer_s{quote.seller_id}_{quote.component}"
            self.final_offers[offer_id] = FinalOffer(
                offer_id=offer_id,
                quote_id=quote.quote_id,
                seller_id=quote.seller_id,
                component=quote.component,
                max_units=counter.units,
                min_units=quote.min_units,
                unit_price=price,
                source=source,
            )
            accepted += 1
            verdicts.append(f"accepted {offer_id}")
        self.phase = "approval"
        return PhaseResult("counter", accepted, rejected, tuple(verdicts))

    def submit_approval_request(
        self, selections: Sequence[OfferSelection]
    ) -> ApprovalDecision:
        if self.phase != "approval":
            raise ValueError("approval may only be requested in the approval phase")
        violations: list[str] = []
        lines: list[procurement.AwardLine] = []
        seen: set[str] = set()
        normalized: list[OfferSelection] = []
        for selection in selections:
            offer = self.final_offers.get(selection.offer_id)
            if (
                offer is None
                or selection.offer_id in seen
                or isinstance(selection.units, bool)
                or not isinstance(selection.units, int)
                or not offer.min_units <= selection.units <= offer.max_units
            ):
                violations.append(f"invalid offer selection: {selection.offer_id}")
                continue
            seen.add(selection.offer_id)
            normalized.append(selection)
            lines.append(
                procurement.AwardLine(
                    seller_id=offer.seller_id,
                    component=offer.component,
                    units=selection.units,
                    unit_price=offer.unit_price,
                )
            )
        validation = procurement.validate_award(
            self.world, lines, signoff_granted=True
        )
        violations.extend(validation.violations)
        payload = [asdict(item) for item in normalized]
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        self.approval = ApprovalDecision(
            approval_id=f"approval_{digest}",
            approved=not violations and validation.ok,
            spend=validation.spend,
            violations=tuple(violations),
            selections=tuple(normalized),
            award_lines=tuple(lines),
        )
        self.phase = "award"
        return self.approval

    def submit_award(self, approval_id: str | None) -> PhaseResult:
        if self.phase != "award":
            raise ValueError("award may only be submitted in the award phase")
        if approval_id is None:
            self.finished = True
            self.phase = "done"
            return PhaseResult("award", 1, 0, ("closed without purchase",))
        if (
            self.approval is None
            or approval_id != self.approval.approval_id
            or not self.approval.approved
        ):
            return PhaseResult("award", 0, 1, ("award lacks matching approval",))
        self.award_lines = self.approval.award_lines
        self.finished = True
        self.phase = "done"
        return PhaseResult("award", 1, 0, ("purchase order executed",))

    def economics(self) -> ProcurementEconomics:
        if not self.finished:
            raise ValueError("economics are available only after termination")
        contact_total = len(self.rfqs) * self.contact_cost
        executed = bool(self.award_lines)
        spend = sum(line.units * line.unit_price for line in self.award_lines)
        production_cost = sum(
            line.units * self.world.supplier(line.seller_id, line.component).unit_cost
            for line in self.award_lines
        )
        if executed:
            buyer_surplus = self.world.demand.contract_value - spend - contact_total
            supplier_margin = spend - production_cost
            social_welfare = self.world.demand.contract_value - production_cost - contact_total
        else:
            buyer_surplus = -contact_total
            supplier_margin = 0.0
            social_welfare = -contact_total
        upper = buyer_surplus_upper_bound(
            self.world,
            max_contacts=self.max_contacts,
            contact_cost=self.contact_cost,
        )
        score = buyer_surplus / upper if upper > 1e-9 else None
        disclosure_uplift = sum(
            quote.disclosure_uplift * quote.max_units
            for quote in self.opening_quotes.values()
        )
        return ProcurementEconomics(
            executed=executed,
            spend=spend,
            production_cost=production_cost,
            contact_cost_total=contact_total,
            buyer_surplus=buyer_surplus,
            supplier_margin=supplier_margin,
            social_welfare=social_welfare,
            buyer_surplus_upper_bound=upper,
            buyer_surplus_score=score,
            disclosed_rfq_count=sum(
                request.disclosed_target_unit_price is not None
                for request in self.rfqs.values()
            ),
            disclosure_quote_uplift=disclosure_uplift,
            contacted_supplier_ids=tuple(
                sorted({request.seller_id for request in self.rfqs.values()})
            ),
            approval_granted=bool(self.approval and self.approval.approved),
            violations=self.approval.violations if self.approval else (),
        )


def _baseline_contact_drafts(
    world: procurement.ProcurementWorld, max_contacts: int
) -> list[RFQDraft]:
    eligible = [
        terms
        for terms in world.suppliers
        if terms.seller_id in world.authz.approved_vendors
        and terms.lead_time_days <= world.demand.deadline_days
    ]
    eligible.sort(key=lambda item: (item.component, item.seller_id))
    return [
        RFQDraft(
            terms.seller_id,
            terms.component,
            world.demand.units_required[terms.component],
        )
        for terms in eligible[:max_contacts]
    ]


def _solve_offer_selections(
    market: ProcurementRFQMarket,
) -> list[OfferSelection]:
    prices = {
        (offer.seller_id, offer.component): offer.unit_price
        for offer in market.final_offers.values()
    }
    oracle = procurement.solve_min_cost_award(_priced_world(market.world, prices))
    if not oracle.feasible:
        return []
    offer_by_key = {
        (offer.seller_id, offer.component): offer
        for offer in market.final_offers.values()
    }
    return [
        OfferSelection(
            offer_by_key[(line.seller_id, line.component)].offer_id,
            line.units,
        )
        for line in oracle.lines
    ]


def run_scripted_rfq_baseline(
    world: procurement.ProcurementWorld,
    *,
    max_contacts: int,
    contact_cost: float,
    disclosure_anchor: float,
) -> ProcurementEconomics:
    """Executable visible-terms baseline with no private-cost access.

    It filters the public directory, requests quotes without disclosing a target,
    counters at 80% of each opening quote, and chooses the cheapest feasible final
    award.  The 80% rule is intentionally simple and versioned; it is a comparison
    policy, not an oracle.
    """
    market = ProcurementRFQMarket(
        world,
        max_contacts=max_contacts,
        contact_cost=contact_cost,
        disclosure_anchor=disclosure_anchor,
    )
    market.submit_rfqs(_baseline_contact_drafts(world, max_contacts))
    market.submit_quotes(
        {
            request.seller_id: market.scripted_quote_action(request.request_id)
            for request in market.rfqs.values()
        }
    )
    market.submit_counters(
        [
            CounterDraft(
                quote.quote_id,
                quote.max_units,
                _floor_money(quote.unit_price * 0.8),
            )
            for quote in market.opening_quotes.values()
        ]
    )
    market.submit_counter_responses(
        {
            counter.seller_id: market.scripted_counter_action(counter.counter_id)
            for counter in market.counters.values()
        }
    )
    approval = market.submit_approval_request(_solve_offer_selections(market))
    market.submit_award(approval.approval_id if approval.approved else None)
    return market.economics()


__all__ = [
    "ApprovalDecision",
    "CounterDraft",
    "CounterOffer",
    "CounterResponseAction",
    "FinalOffer",
    "OfferSelection",
    "PhaseResult",
    "ProcurementEconomics",
    "ProcurementRFQMarket",
    "RFQDraft",
    "RFQRequest",
    "VendorQuote",
    "VendorQuoteAction",
    "buyer_surplus_upper_bound",
    "run_scripted_rfq_baseline",
    "scripted_opening_price",
    "supplier_floor_price",
    "world_from_payload",
    "world_to_payload",
]
