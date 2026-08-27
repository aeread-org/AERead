"""Red/green contract tests for the production-shaped procurement RFQ case."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from aeread import exchange_procurement as procurement
from aeread import procurement_rfq_env as rfq


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "exchange_economy" / "procurement_electronics_q3.json"


def _world() -> procurement.ProcurementWorld:
    return procurement.load_procurement_world(CONFIG_PATH)


def _market() -> rfq.ProcurementRFQMarket:
    return rfq.ProcurementRFQMarket(
        _world(),
        max_contacts=5,
        contact_cost=5.0,
        disclosure_anchor=0.95,
    )


def _send_feasible_rfqs(
    market: rfq.ProcurementRFQMarket,
    *,
    disclosed_chip_target: float | None = None,
) -> None:
    result = market.submit_rfqs(
        [
            rfq.RFQDraft(2, "chips", 60, disclosed_chip_target),
            rfq.RFQDraft(3, "chips", 40),
            rfq.RFQDraft(5, "pcb", 100),
            rfq.RFQDraft(7, "enclosure", 100),
        ]
    )
    assert result.accepted == 4
    assert result.rejected == 0


def _submit_scripted_quotes(market: rfq.ProcurementRFQMarket) -> None:
    responses = {
        request.seller_id: market.scripted_quote_action(request.request_id)
        for request in market.rfqs.values()
    }
    result = market.submit_quotes(responses)
    assert result.accepted == len(responses)


def _counter_to_supplier_floors(market: rfq.ProcurementRFQMarket) -> None:
    counters = []
    for quote in market.opening_quotes.values():
        terms = market.world.supplier(quote.seller_id, quote.component)
        counters.append(
            rfq.CounterDraft(
                quote_id=quote.quote_id,
                units=quote.max_units,
                unit_price=rfq.supplier_floor_price(terms),
            )
        )
    result = market.submit_counters(counters)
    assert result.accepted == len(counters)
    responses = {
        counter.seller_id: market.scripted_counter_action(counter.counter_id)
        for counter in market.counters.values()
    }
    result = market.submit_counter_responses(responses)
    assert result.accepted == len(responses)


def _efficient_selections(market: rfq.ProcurementRFQMarket) -> list[rfq.OfferSelection]:
    by_key = {
        (offer.seller_id, offer.component): offer
        for offer in market.final_offers.values()
    }
    return [
        rfq.OfferSelection(by_key[(2, "chips")].offer_id, 60),
        rfq.OfferSelection(by_key[(3, "chips")].offer_id, 40),
        rfq.OfferSelection(by_key[(5, "pcb")].offer_id, 100),
        rfq.OfferSelection(by_key[(7, "enclosure")].offer_id, 100),
    ]


def test_buyer_and_vendor_observations_preserve_private_costs() -> None:
    market = _market()
    buyer = market.buyer_observation()

    assert buyer["mandate"]["budget"] == 2400.0
    assert {row["seller_id"] for row in buyer["vendor_directory"]} == set(range(2, 9))
    assert "unit_cost" not in str(buyer)

    _send_feasible_rfqs(market, disclosed_chip_target=15.0)
    seller = market.vendor_observation(2)
    assert seller["private_unit_cost"] == 10.0
    assert seller["rfq"]["disclosed_target_unit_price"] == 15.0
    assert "private_unit_cost" not in str(market.vendor_observation(3)["rfq"])


def test_disclosing_target_price_raises_the_controlled_vendor_quote() -> None:
    concealed = _market()
    _send_feasible_rfqs(concealed)
    concealed_action = concealed.scripted_quote_action(
        next(request.request_id for request in concealed.rfqs.values() if request.seller_id == 2)
    )

    disclosed = _market()
    _send_feasible_rfqs(disclosed, disclosed_chip_target=15.0)
    disclosed_action = disclosed.scripted_quote_action(
        next(request.request_id for request in disclosed.rfqs.values() if request.seller_id == 2)
    )

    assert concealed_action.unit_price == pytest.approx(13.50)
    assert disclosed_action.unit_price == pytest.approx(14.25)
    assert disclosed_action.unit_price > concealed_action.unit_price


def test_full_rfq_lifecycle_reaches_approval_and_binding_purchase() -> None:
    market = _market()
    _send_feasible_rfqs(market)
    _submit_scripted_quotes(market)
    _counter_to_supplier_floors(market)

    approval = market.submit_approval_request(_efficient_selections(market))
    assert approval.approved is True
    assert approval.violations == ()
    assert approval.spend == pytest.approx(2184.0)

    wrong = market.submit_award("approval_unknown")
    assert wrong.accepted == 0
    assert market.finished is False

    result = market.submit_award(approval.approval_id)
    assert result.accepted == 1
    assert market.finished is True

    economics = market.economics()
    assert economics.executed is True
    assert economics.contact_cost_total == pytest.approx(20.0)
    assert economics.buyer_surplus == pytest.approx(796.0)
    assert economics.supplier_margin == pytest.approx(104.0)
    assert economics.social_welfare == pytest.approx(900.0)
    assert economics.buyer_surplus_upper_bound == pytest.approx(796.0)
    assert economics.buyer_surplus_score == pytest.approx(1.0)
    assert economics.disclosed_rfq_count == 0


def test_approver_denies_off_list_award_and_purchase_cannot_execute() -> None:
    market = _market()
    result = market.submit_rfqs(
        [
            rfq.RFQDraft(8, "chips", 100),
            rfq.RFQDraft(5, "pcb", 100),
            rfq.RFQDraft(7, "enclosure", 100),
        ]
    )
    assert result.accepted == 3
    _submit_scripted_quotes(market)
    market.submit_counters([])
    market.submit_counter_responses({})
    selections = [
        rfq.OfferSelection(offer.offer_id, 100)
        for offer in market.final_offers.values()
    ]

    approval = market.submit_approval_request(selections)
    assert approval.approved is False
    assert any(procurement.V_OFF_LIST in violation for violation in approval.violations)

    result = market.submit_award(approval.approval_id)
    assert result.accepted == 0
    assert market.finished is False


def test_scripted_baseline_is_executable_and_below_full_information_terms_bound() -> None:
    baseline = rfq.run_scripted_rfq_baseline(
        _world(),
        max_contacts=5,
        contact_cost=5.0,
        disclosure_anchor=0.95,
    )

    assert baseline.executed is True
    assert 0.0 < baseline.buyer_surplus < baseline.buyer_surplus_upper_bound
    assert 0.8 < baseline.buyer_surplus_score < 1.0
    assert baseline.disclosed_rfq_count == 0


def _contact_tradeoff_world() -> procurement.ProcurementWorld:
    world = procurement.make_random_procurement_world(components=1, seed=0)
    return replace(
        world,
        suppliers=[
            replace(world.suppliers[0], unit_cost=10.0, lead_time_days=20, moq=1),
            replace(world.suppliers[1], unit_cost=10.01, lead_time_days=20, moq=1),
        ],
    )


@pytest.mark.parametrize("max_contacts", [1, 2])
def test_upper_bound_jointly_optimizes_spend_and_contact_cost(max_contacts) -> None:
    world = _contact_tradeoff_world()
    # Splitting costs 1051 + 10 in contacts; vendor 3 alone costs 1052 + 5.
    assert rfq.buyer_surplus_upper_bound(
        world, max_contacts=max_contacts, contact_cost=5.0
    ) == pytest.approx(943.0)


def test_executable_single_vendor_purchase_cannot_exceed_bound() -> None:
    market = rfq.ProcurementRFQMarket(
        _contact_tradeoff_world(), max_contacts=2, contact_cost=5.0, disclosure_anchor=0.95
    )
    market.submit_rfqs([rfq.RFQDraft(3, "c1", 100)])
    _submit_scripted_quotes(market)
    _counter_to_supplier_floors(market)
    offer = next(iter(market.final_offers.values()))
    approval = market.submit_approval_request([rfq.OfferSelection(offer.offer_id, 100)])
    assert approval.approved
    market.submit_award(approval.approval_id)
    economics = market.economics()
    assert economics.buyer_surplus == pytest.approx(943.0)
    assert economics.buyer_surplus <= economics.buyer_surplus_upper_bound
    assert economics.buyer_surplus_score == pytest.approx(1.0)


def test_upper_bound_includes_no_trade_when_contacts_erase_the_gain() -> None:
    world = _contact_tradeoff_world()
    world = replace(world, demand=replace(world.demand, contract_value=1000.0))
    assert rfq.buyer_surplus_upper_bound(
        world, max_contacts=2, contact_cost=5.0
    ) == 0.0
