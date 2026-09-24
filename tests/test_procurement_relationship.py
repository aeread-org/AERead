"""Repeated sourcing: the period loop, the T-period bound, and the six worlds.

The single-period family must be untouched: a case without ``periods`` keeps
its observation shape, its bound and its scores. Under a declared block the
award becomes a period transition, and the exact bound must be *attainable*:
replaying its plan through the environment reaches it to the cent.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
from pathlib import Path

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation import (
    RELATIONSHIP_PROMPT,
    ProcurementAllocationPlugin,
    finalize_procurement_allocation_execution,
    load_case,
    replay_procurement_allocation_receipt,
    run_fixture_script,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation import environment as env
from aeread_families.procurement_allocation import relationship as rel
from aeread_families.procurement_allocation.headroom_screen import (
    ADMIT,
    FLOORED,
    TRIVIAL_LOYAL,
    TRIVIAL_MYOPIC,
    UNMEASURED,
    classify_relationship_world,
    replay_baseline_outcome,
)
from aeread_families.procurement_allocation.relationship_case_matrix import (
    CASE_PATHS,
    CASE_SLUGS,
    build_case_matrix,
    screen_world,
)

ROOT = Path(__file__).resolve().parents[1]
DEV_CASE = ROOT / "cases" / "procurement_allocation_v1" / "dev" / "deadline_cost.json"
PROGRAMME = {
    "loyalty_discount_per_award": 0.05,
    "loyalty_discount_cap": 0.15,
    "incumbent_capacity_bonus": 10,
    "retaliation_markup": 0.10,
}


def _dev_payload() -> dict:
    return copy.deepcopy(json.loads(DEV_CASE.read_text(encoding="utf-8"))["payload"])


def _period_payload(count: int = 3, *, programme: dict | None = PROGRAMME) -> dict:
    payload = _dev_payload()
    payload["interaction"]["periods"] = {"count": count, "delivery_seed": 7}
    if programme is not None:
        for supplier in payload["suppliers"]:
            supplier["private_terms"]["relationship"] = dict(programme)
    return payload


class _Episode:
    """Drive the plugin directly, one parsed and legality-checked action at a time."""

    def __init__(self, payload: dict) -> None:
        self.plugin = ProcurementAllocationPlugin()
        self.case = self.plugin.validate_payload(payload)
        self.phase = self.plugin.phases(self.case)[0]
        self.state = self.plugin.initial_state(self.case, None)

    def observe(self) -> dict:
        return self.plugin.observe(self.case, self.state, "buyer", self.phase)

    def play(self, action: dict):
        parsed = self.plugin.parse_action(self.case, self.state, "buyer", self.phase, action)
        legality = (
            self.plugin.legal(self.case, self.state, "buyer", self.phase, parsed.action)
            if parsed.ok
            else None
        )
        envelope = ActionEnvelope(
            "buyer",
            bool(parsed.ok and legality.legal),
            parsed.action if parsed.ok else None,
            parsed,
            legality,
        )
        result = self.plugin.step(self.case, self.state, self.phase, {"buyer": envelope})
        self.state = result.state
        return result

    def quote(self, supplier_id: str) -> str:
        self.play({"action": "request_quote", "supplier_id": supplier_id, "message": "quote"})
        return self.state["latest_offer_by_supplier"][supplier_id]

    def sample(self, supplier_id: str) -> None:
        self.play({"action": "request_sample", "supplier_id": supplier_id, "message": "sample"})

    def award(self, lines: list[dict]):
        return self.play({"action": "submit_award", "award_lines": lines})

    def outcome(self) -> dict:
        terminal = self.plugin.terminal(self.case, self.state)
        assert terminal is not None
        return self.plugin.outcome(self.case, terminal)


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


def test_single_period_case_is_unchanged() -> None:
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(_dev_payload())
    state = plugin.initial_state(case, None)
    observation = plugin.observe(case, state, "buyer", plugin.phases(case)[0])
    assert "period" not in observation and "history" not in observation
    assert "period" not in state and "relationship" not in state
    assert plugin.phases(case)[0].max_logical_actions == 10
    assert not rel.periods_declared(case)


def test_relationship_terms_require_a_periods_block() -> None:
    payload = _dev_payload()
    payload["suppliers"][0]["private_terms"]["relationship"] = dict(PROGRAMME)
    with pytest.raises(ValueError, match="requires interaction.periods"):
        ProcurementAllocationPlugin().validate_payload(payload)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update({"count": 1}), "between 2 and 8"),
        (lambda p: p.update({"count": 9}), "between 2 and 8"),
        (lambda p: p.pop("delivery_seed"), "requires 'count' and 'delivery_seed'"),
        (lambda p: p.update({"extra": 1}), "permits only 'overrides'"),
        (lambda p: p.update({"overrides": [{}]}), "one object per period"),
        (
            lambda p: p.update({"overrides": [{"bom": {}}, {}, {}]}),
            "unsupported fields",
        ),
        (
            lambda p: p.update({"overrides": [{"target_kits": 5}, {}, {}]}),
            "minimum_service_kits above target_kits",
        ),
    ],
)
def test_periods_block_is_validated(mutate, message: str) -> None:
    payload = _period_payload()
    mutate(payload["interaction"]["periods"])
    with pytest.raises(ValueError, match=message):
        ProcurementAllocationPlugin().validate_payload(payload)


def test_relationship_block_must_be_complete_and_bounded() -> None:
    payload = _period_payload()
    payload["suppliers"][0]["private_terms"]["relationship"].pop("retaliation_markup")
    with pytest.raises(ValueError, match="must declare exactly"):
        ProcurementAllocationPlugin().validate_payload(payload)
    payload = _period_payload()
    payload["suppliers"][0]["private_terms"]["relationship"]["loyalty_discount_cap"] = 0.95
    with pytest.raises(ValueError, match="loyalty_discount_cap"):
        ProcurementAllocationPlugin().validate_payload(payload)
    payload = _period_payload()
    payload["suppliers"][0]["private_terms"]["relationship"]["incumbent_capacity_bonus"] = -1
    with pytest.raises(ValueError, match="incumbent_capacity_bonus"):
        ProcurementAllocationPlugin().validate_payload(payload)


def test_period_objective_applies_overrides_in_order() -> None:
    payload = _period_payload()
    payload["interaction"]["periods"]["overrides"] = [
        {},
        {"target_kits": 30, "minimum_service_kits": 24, "cash_budget_usd": 300.0},
        {},
    ]
    case = ProcurementAllocationPlugin().validate_payload(payload)
    schedule = rel.period_schedule(case)
    assert [row["target_kits"] for row in schedule] == [20, 30, 20]
    assert schedule[1]["cash_budget_usd"] == 300.0
    assert schedule[0]["cash_budget_usd"] == payload["objective"]["cash_budget_usd"]


# --------------------------------------------------------------------------
# Standing and effective terms
# --------------------------------------------------------------------------


def test_effective_supplier_moves_quote_floor_and_capacity_together() -> None:
    supplier = _period_payload()["suppliers"][0]
    base = supplier["private_terms"]
    fresh = rel.effective_supplier(supplier, {"consecutive_awards": 0, "retaliation_periods_left": 0})
    assert fresh["private_terms"]["base_unit_price_usd"] == base["base_unit_price_usd"]
    assert fresh["private_terms"]["capacity"] == base["capacity"]
    assert fresh["relationship_applied"]["loyalty_discount"] == 0.0

    loyal = rel.effective_supplier(supplier, {"consecutive_awards": 2, "retaliation_periods_left": 0})
    assert loyal["private_terms"]["base_unit_price_usd"] == pytest.approx(
        base["base_unit_price_usd"] * 0.90
    )
    assert loyal["private_terms"]["negotiation"]["floor_unit_price_usd"] == pytest.approx(
        base["negotiation"]["floor_unit_price_usd"] * 0.90
    )
    assert loyal["private_terms"]["capacity"] == base["capacity"] + 10

    capped = rel.effective_supplier(supplier, {"consecutive_awards": 9, "retaliation_periods_left": 0})
    assert capped["relationship_applied"]["loyalty_discount"] == 0.15

    dropped = rel.effective_supplier(supplier, {"consecutive_awards": 0, "retaliation_periods_left": 1})
    assert dropped["private_terms"]["base_unit_price_usd"] == pytest.approx(
        base["base_unit_price_usd"] * 1.10
    )
    assert dropped["private_terms"]["capacity"] == base["capacity"]


def test_supplier_without_a_programme_is_left_alone() -> None:
    supplier = _dev_payload()["suppliers"][0]
    moved = rel.effective_supplier(supplier, {"consecutive_awards": 3, "retaliation_periods_left": 1})
    assert moved == supplier
    assert rel.relationship_applied(supplier, {"consecutive_awards": 3, "retaliation_periods_left": 1}) is None


def test_standing_transition_rules() -> None:
    entry = {"consecutive_awards": 2, "retaliation_periods_left": 0}
    assert rel.advance_entry(entry, awarded=True, quoted=True) == {
        "consecutive_awards": 3,
        "retaliation_periods_left": 0,
    }
    assert rel.advance_entry(entry, awarded=False, quoted=True) == {
        "consecutive_awards": 0,
        "retaliation_periods_left": 1,
    }
    lapsing = {"consecutive_awards": 0, "retaliation_periods_left": 1}
    assert rel.advance_entry(lapsing, awarded=False, quoted=False) == {
        "consecutive_awards": 0,
        "retaliation_periods_left": 0,
    }
    # An award forgives a grievance.
    assert rel.advance_entry(lapsing, awarded=True, quoted=True)["retaliation_periods_left"] == 0


def test_realized_delivery_is_seeded_and_deadline_aware() -> None:
    case = ProcurementAllocationPlugin().validate_payload(_period_payload())
    supplier = case["suppliers"][0]
    offer = env._base_offer(supplier, version=1, issued_day=0)
    lines = [{"offer_id": offer["offer_id"], "quantity": 20}]
    first, kits = rel.realize_delivery(
        case, period=1, award_lines=lines, offers={offer["offer_id"]: offer}, elapsed_days=0
    )
    again, _ = rel.realize_delivery(
        case, period=1, award_lines=lines, offers={offer["offer_id"]: offer}, elapsed_days=0
    )
    assert first == again
    assert kits == 0  # one component of two delivered, no kit completes
    late, _ = rel.realize_delivery(
        case,
        period=1,
        award_lines=lines,
        offers={offer["offer_id"]: offer},
        elapsed_days=case["objective"]["deadline_days"],
    )
    assert late[0]["on_time"] is False and late[0]["good_units_delivered"] == 0


# --------------------------------------------------------------------------
# The period loop in the environment
# --------------------------------------------------------------------------


def test_award_closes_a_period_and_standing_shows_in_the_next_quote() -> None:
    episode = _Episode(_period_payload(count=3))
    controllers, displays = "esp32_s3_n8r8_express", "ssd1306_oled_096_express"
    assert episode.phase.max_logical_actions == 30

    first = episode.quote(controllers)
    assert episode.state["offers"][first]["relationship"]["consecutive_awards"] == 0
    episode.sample(controllers)
    second = episode.quote(displays)
    episode.sample(displays)
    result = episode.award([{"offer_id": first, "quantity": 20}, {"offer_id": second, "quantity": 20}])

    assert result.consequences["period_closed"] == 1
    assert result.consequences["period_decision"] == "award"
    assert result.next_phase_id == env.PHASE_ID
    assert episode.state["done"] is False
    assert episode.state["period"] == 2
    assert episode.state["actions_used"] == 0 and episode.state["total_actions_used"] == 5
    assert episode.state["offers"] == {} and episode.state["elapsed_days"] == 0
    assert set(episode.state["quality_evidence"]) == {controllers, displays}
    assert episode.state["relationship"][controllers] == {
        "consecutive_awards": 1,
        "retaliation_periods_left": 0,
    }

    observation = episode.observe()
    assert observation["period"] == 2 and observation["periods"] == 3
    assert len(observation["history"]) == 1
    delivery = observation["history"][0]["delivery"]
    assert {row["supplier_id"] for row in delivery} == {controllers, displays}
    assert "contribution_margin_usd" not in observation["history"][0]

    renewed = episode.quote(controllers)
    offer = episode.state["offers"][renewed]
    base_price = episode.case["suppliers"][1]["private_terms"]["base_unit_price_usd"]
    assert offer["relationship"]["consecutive_awards"] == 1
    assert offer["unit_price_usd"] == pytest.approx(base_price * 0.95)
    assert offer["capacity"] == 30


def test_quoted_then_dropped_supplier_retaliates_for_one_period() -> None:
    episode = _Episode(_period_payload(count=3))
    spot, partner = "esp32_s3_n8r8_value", "esp32_s3_n8r8_express"
    display = "ssd1306_oled_096_express"
    episode.quote(spot)  # shopped, never awarded
    partner_offer = episode.quote(partner)
    episode.sample(partner)
    display_offer = episode.quote(display)
    episode.sample(display)
    episode.award([{"offer_id": partner_offer, "quantity": 20}, {"offer_id": display_offer, "quantity": 20}])
    assert episode.state["relationship"][spot] == {
        "consecutive_awards": 0,
        "retaliation_periods_left": 1,
    }
    spot_price = episode.case["suppliers"][0]["private_terms"]["base_unit_price_usd"]
    renewed = episode.quote(spot)
    marked_up = episode.state["offers"][renewed]
    assert marked_up["unit_price_usd"] == pytest.approx(spot_price * 1.10)
    assert marked_up["relationship"]["retaliation_markup"] == 0.10
    # Not approached again in period 2, the grievance lapses at its close.
    episode.play({"action": "defer", "reason": "skip this period"})
    assert episode.state["period"] == 3
    assert episode.state["relationship"][spot]["retaliation_periods_left"] == 1
    # Quoted and dropped again in period 2 (the quote above), so it holds for period 3.
    episode.play({"action": "defer", "reason": "skip the last period too"})
    assert episode.state["done"] is True
    assert episode.state["termination_reason"] == "deferred"


def test_defer_and_budget_exhaustion_end_a_period_not_the_episode() -> None:
    episode = _Episode(_period_payload(count=2))
    episode.play({"action": "defer", "reason": "wait"})
    assert episode.state["period"] == 2 and episode.state["done"] is False
    assert episode.state["history"][0]["decision"] == "defer"
    for _ in range(10):
        episode.play(
            {
                "action": "inquire",
                "supplier_id": "esp32_s3_n8r8_value",
                "fields": ["exact_variant"],
                "message": "again",
            }
        )
    assert episode.state["done"] is True
    assert episode.state["termination_reason"] == "interaction_budget_exhausted"
    outcome = episode.outcome()
    assert outcome["period_decisions"] == ["defer", "failed"]
    assert outcome["feasible"] is False and outcome["feasible_award"] is False
    assert outcome["contribution_margin_usd"] == pytest.approx(-0.5)  # ten inquiries at $0.05
    assert outcome["action_count"] == 11
    assert outcome["violations"] == ["period_2:interaction_budget_exhausted"]


def test_invalid_action_forfeits_the_remaining_periods() -> None:
    episode = _Episode(_period_payload(count=3))
    episode.quote("esp32_s3_n8r8_value")
    episode.play({"action": "submit_award", "award_lines": [{"offer_id": "nope", "quantity": 20}]})
    # An unknown offer is a rejected award, which closes period 1 as infeasible.
    assert episode.state["period"] == 2
    assert episode.state["history"][0]["feasible"] is False
    episode.play({"action": "counter_offer", "supplier_id": "x", "offer_id": "y", "proposal": {}, "message": "m"})
    assert episode.state["done"] and episode.state["termination_reason"] == "invalid_action"
    outcome = episode.outcome()
    assert outcome["period_decisions"] == ["award", "failed", "unplayed"]
    assert outcome["decision"] == "failed"
    assert outcome["contribution_margin_usd"] == pytest.approx(-0.1)
    assert outcome["upper_bound_usd"] > 0
    assert outcome["regret_to_upper_bound_usd"] == pytest.approx(outcome["upper_bound_usd"] + 0.1)


# --------------------------------------------------------------------------
# The bound and its references
# --------------------------------------------------------------------------


def _tiny_world() -> dict:
    """One component, two suppliers, one admissible quantity each, three periods."""
    payload = _period_payload(count=3, programme=None)
    payload["objective"]["bom"] = {"esp32_s3_n8r8": 1}
    payload["policy"]["required_variant_by_component"] = {
        "esp32_s3_n8r8": payload["policy"]["required_variant_by_component"]["esp32_s3_n8r8"]
    }
    payload["objective"]["deadline_days"] = 60
    payload["objective"]["cash_budget_usd"] = 500.0
    payload["suppliers"] = [
        supplier for supplier in payload["suppliers"] if supplier["component"] == "esp32_s3_n8r8"
    ]
    for supplier in payload["suppliers"]:
        terms = supplier["private_terms"]
        terms["capacity"] = terms["moq"] = terms["order_step"] = 20
        terms["negotiation"]["minimum_moq"] = 20
    # The express supplier is three percent dearer today and discounts ten
    # percent per consecutive award: dearer in period one, cheaper over three.
    express = payload["suppliers"][1]["private_terms"]
    express["base_unit_price_usd"] = 3.30
    express["negotiation"]["floor_unit_price_usd"] = round(3.30 * 0.94, 6)
    express["relationship"] = {
        "loyalty_discount_per_award": 0.10,
        "loyalty_discount_cap": 0.20,
        "incumbent_capacity_bonus": 0,
        "retaliation_markup": 0.0,
    }
    return payload


def test_bound_matches_brute_force_on_a_tiny_world() -> None:
    case = ProcurementAllocationPlugin().validate_payload(_tiny_world())
    interaction = case["interaction"]
    choices = [None] + [
        (index, mode) for index in range(len(case["suppliers"])) for mode in ("base", "negotiated")
    ]
    best = None
    for sequence in itertools.product(choices, repeat=3):
        standing = {
            str(supplier["supplier_id"]): {"consecutive_awards": 0, "retaliation_periods_left": 0}
            for supplier in case["suppliers"]
        }
        qualified: set[str] = set()
        total = 0.0
        feasible = True
        for period, choice in enumerate(sequence, start=1):
            if choice is None:
                total += case["objective"]["defer_value_usd"]
                standing = {
                    key: rel.advance_entry(entry, awarded=False, quoted=False)
                    for key, entry in standing.items()
                }
                continue
            index, mode = choice
            supplier = case["suppliers"][index]
            supplier_id = str(supplier["supplier_id"])
            moved = rel.effective_supplier(supplier, standing[supplier_id])
            offer = (
                env._base_offer(moved, version=1, issued_day=0)
                if mode == "base"
                else env._best_offer(moved, version=2, issued_day=0)
            )
            quality = supplier["private_terms"]["quality"]
            needs_sample = supplier_id not in qualified
            elapsed = interaction["quote_days"] + (quality["sample_lead_time_days"] if needs_sample else 0)
            cost = interaction["quote_cost_usd"] + (quality["sample_cost_usd"] if needs_sample else 0.0)
            if mode == "negotiated":
                elapsed += interaction["counter_days"]
                cost += interaction["counter_cost_usd"]
            result = env.evaluate_award(
                rel.period_case(case, period),
                award_lines=[{"offer_id": offer["offer_id"], "quantity": 20}],
                offers={offer["offer_id"]: offer},
                quality_evidence={
                    supplier_id: {
                        **quality,
                        "supplier_id": supplier_id,
                        "variant_id": supplier["private_terms"]["variant_id"],
                        "evidence_status": "verified_sample",
                    }
                },
                elapsed_days=elapsed,
                information_cost_usd=round(cost, 8),
            )
            if not result["feasible"]:
                feasible = False
                break
            total += result["contribution_margin_usd"]
            qualified.add(supplier_id)
            standing = {
                key: rel.advance_entry(entry, awarded=key == supplier_id, quoted=key == supplier_id)
                for key, entry in standing.items()
            }
        if feasible and (best is None or total > best):
            best = total
    bound = rel.solve_relationship_upper_bound(case)
    assert bound.contribution_margin_usd == pytest.approx(best, abs=1e-6)
    # The programme makes the dearer supplier the better relationship.
    assert [plan[0]["supplier_id"] for plan in bound.period_plans] == ["esp32_s3_n8r8_express"] * 3


def test_references_never_exceed_the_bound_and_periods_beat_repetition() -> None:
    for path in CASE_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        bound = rel.solve_relationship_upper_bound(payload)
        myopic = rel.solve_myopic_reference(payload)
        loyal = rel.solve_loyal_reference(payload)
        assert myopic.contribution_margin_usd <= bound.contribution_margin_usd + 1e-6
        assert loyal.contribution_margin_usd <= bound.contribution_margin_usd + 1e-6
        # Repeating the single-period optimum is feasible over the horizon and
        # never dearer, since standing only lowers a re-awarded supplier's
        # schedule and a sample is paid once; the T-period bound must dominate.
        single = copy.deepcopy(payload)
        periods = single["interaction"].pop("periods")
        if periods.get("overrides"):
            continue
        for supplier in single["suppliers"]:
            supplier["private_terms"].pop("relationship", None)
        repeated = solve_full_information_upper_bound(single).contribution_margin_usd * periods["count"]
        assert bound.contribution_margin_usd >= repeated - 1e-6


def test_relationship_screen_verdicts() -> None:
    kwargs = dict(upper_bound=100.0, outside_option=0.0)
    assert classify_relationship_world(myopic=90.0, loyal=80.0, **kwargs) == ADMIT
    assert classify_relationship_world(myopic=96.0, loyal=80.0, **kwargs) == TRIVIAL_MYOPIC
    assert classify_relationship_world(myopic=90.0, loyal=97.0, **kwargs) == TRIVIAL_LOYAL
    assert classify_relationship_world(upper_bound=0.0, myopic=0.0, loyal=0.0, outside_option=0.0) == FLOORED
    assert classify_relationship_world(myopic=float("nan"), loyal=80.0, **kwargs) == UNMEASURED
    with pytest.raises(ValueError, match="not a bound"):
        classify_relationship_world(myopic=101.0, loyal=80.0, **kwargs)


# --------------------------------------------------------------------------
# The panel
# --------------------------------------------------------------------------


def test_panel_regenerates_to_the_committed_bytes() -> None:
    built = {case["case_id"].rsplit(".", 1)[-1]: case for case in build_case_matrix()}
    assert tuple(built) == CASE_SLUGS
    for path in CASE_PATHS:
        committed = json.loads(path.read_text(encoding="utf-8"))
        assert canonical_json_bytes(built[path.stem]) == canonical_json_bytes(committed)
        assert committed["episode"]["max_logical_actions"] == 40
        assert committed["payload"]["interaction"]["periods"]["count"] == 4


@pytest.mark.parametrize("path", CASE_PATHS, ids=lambda p: p.stem)
def test_every_world_admits_and_its_bound_is_attainable(path: Path, tmp_path: Path) -> None:
    """Replay the bound's own plan through the environment and reach it."""
    payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
    verdict = screen_world(payload)
    assert verdict["verdict"] == ADMIT
    bound = rel.solve_relationship_upper_bound(payload)
    episode = _Episode(payload)
    for plan in bound.period_plans:
        lines = []
        for line in plan:
            supplier_id = line["supplier_id"]
            offer_id = episode.quote(supplier_id)
            if line["mode"] == "negotiated":
                offer = episode.state["offers"][offer_id]
                result = episode.play(
                    {
                        "action": "counter_offer",
                        "supplier_id": supplier_id,
                        "offer_id": offer_id,
                        "proposal": {
                            "unit_price_usd": line["unit_price_usd"],
                            "moq": offer["moq"],
                            "payment_terms_days": 60,
                            "refund_window_days": 45,
                            "return_freight_payer": "supplier",
                        },
                        "message": "to the floor",
                    }
                )
                assert result.consequences["accepted"] is True, result.consequences
                offer_id = episode.state["latest_offer_by_supplier"][supplier_id]
            if supplier_id not in episode.state["quality_evidence"]:
                episode.sample(supplier_id)
            lines.append({"offer_id": offer_id, "quantity": line["quantity"]})
        if lines:
            episode.award(lines)
        else:
            episode.play({"action": "defer", "reason": "the bound defers here"})
    assert episode.state["done"]
    outcome = episode.outcome()
    assert outcome["feasible_award"] is True
    assert outcome["contribution_margin_usd"] == pytest.approx(bound.contribution_margin_usd, abs=1e-6)
    assert outcome["regret_to_upper_bound_usd"] == pytest.approx(0.0, abs=1e-6)
    assert outcome["switches"] == bound.switches
    assert outcome["myopic_reference_usd"] == verdict["myopic_usd"]


def test_public_policies_play_every_period() -> None:
    payload = json.loads(CASE_PATHS[0].read_text(encoding="utf-8"))["payload"]
    outcome = replay_baseline_outcome(payload, "displayed_price_greedy")
    assert outcome is not None
    assert outcome["periods"] == 4
    assert len(outcome["period_decisions"]) == 4
    assert outcome["contribution_margin_usd"] <= outcome["upper_bound_usd"]


# --------------------------------------------------------------------------
# Through the kernel
# --------------------------------------------------------------------------


def _kernel_script() -> list[str]:
    """Four periods on the loyalty world: quote, sample once, award the partner."""
    actions: list[dict] = []
    versions = {"esp32_s3_n8r8_partner": 0, "ssd1306_oled_096_steady": 0}
    for period in range(1, 5):
        lines = []
        for supplier_id in versions:
            versions[supplier_id] += 1
            actions.append({"action": "request_quote", "supplier_id": supplier_id, "message": "quote"})
            if period == 1:
                actions.append({"action": "request_sample", "supplier_id": supplier_id, "message": "sample"})
            lines.append({"offer_id": f"offer_{supplier_id}_v{versions[supplier_id]}", "quantity": 20})
        actions.append({"action": "submit_award", "award_lines": lines})
    return [json.dumps(action, sort_keys=True) for action in actions]


def test_kernel_runs_four_periods_and_the_receipt_replays(tmp_path: Path) -> None:
    case_path = CASE_PATHS[0]
    setup, execution, provider = asyncio.run(
        run_fixture_script(_kernel_script(), evidence_root=tmp_path / "periods", case_path=case_path)
    )
    assert provider.exhausted
    # Five actions in period one (two quotes, two samples, the award), three
    # in each later period: samples persist, quotes do not.
    assert len(execution.action_executions) == 14
    outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
    assert outcome["periods"] == 4 and outcome["periods_awarded"] == 4
    assert outcome["period_decisions"] == ["award"] * 4
    assert outcome["feasible_award"] is True
    assert outcome["switches"] == 0
    assert 0 < outcome["contribution_margin_usd"] < outcome["upper_bound_usd"]
    receipt = finalize_procurement_allocation_execution(setup=setup, execution=execution)
    assert receipt.status == "ok"
    assert receipt.scores[0].primary.value == pytest.approx(outcome["contribution_margin_usd"])
    replayed = replay_procurement_allocation_receipt(
        setup=setup, receipt=receipt, evidence_root=tmp_path / "periods"
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)
    leaf = receipt.scores[0].leaf
    assert "4 consecutive sourcing periods" in leaf.verifier.objective_scope.horizon


def test_relationship_prompt_extends_the_single_period_prompt() -> None:
    from aeread_families.procurement_allocation import PROMPT

    assert RELATIONSHIP_PROMPT.startswith(PROMPT)
    assert "period_schedule" in RELATIONSHIP_PROMPT
    assert load_case(CASE_PATHS[0]).episode.max_logical_actions == 40


# --------------------------------------------------------------------------
# The shopping reference
# --------------------------------------------------------------------------


def test_shopping_reference_never_beats_myopic_and_pays_only_for_shopping() -> None:
    for path in CASE_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        myopic = rel.solve_myopic_reference(payload)
        shopping = rel.solve_shopping_reference(payload)
        assert shopping.contribution_margin_usd <= myopic.contribution_margin_usd + 1e-6
    # With free instantaneous quotes and no retaliation anywhere, shopping
    # costs nothing and the two references coincide exactly.
    payload = json.loads(CASE_PATHS[0].read_text(encoding="utf-8"))["payload"]
    payload["interaction"]["quote_cost_usd"] = 0.0
    payload["interaction"]["quote_days"] = 1  # validation requires a positive day count
    payload["objective"]["deadline_days"] = 60
    for supplier in payload["suppliers"]:
        supplier["private_terms"]["relationship"]["retaliation_markup"] = 0.0
    case = ProcurementAllocationPlugin().validate_payload(payload)
    assert rel.solve_shopping_reference(case).contribution_margin_usd == pytest.approx(
        rel.solve_myopic_reference(case).contribution_margin_usd, abs=1e-6
    )
    # Retaliation alone separates them once a dropped supplier is priced in.
    for supplier in payload["suppliers"]:
        supplier["private_terms"]["relationship"]["retaliation_markup"] = 0.5
    case = ProcurementAllocationPlugin().validate_payload(payload)
    assert rel.solve_shopping_reference(case).contribution_margin_usd <= rel.solve_myopic_reference(
        case
    ).contribution_margin_usd


def test_outcome_and_screen_carry_the_shopping_reference() -> None:
    payload = json.loads(CASE_PATHS[4].read_text(encoding="utf-8"))["payload"]
    verdict = screen_world(payload)
    assert verdict["shopping_usd"] <= verdict["myopic_usd"]
    episode = _Episode(payload)
    episode.play({"action": "defer", "reason": "skip"})
    for _ in range(3):
        episode.play({"action": "defer", "reason": "skip"})
    outcome = episode.outcome()
    assert outcome["shopping_reference_usd"] == verdict["shopping_usd"]


# --------------------------------------------------------------------------
# Generated packs: selected by rule, noisy verification, disjoint domains
# --------------------------------------------------------------------------

from aeread_families.procurement_allocation.relationship_case_matrix import (  # noqa: E402
    COMPETENT_BASELINE,
    PACKS,
    PACK_GENERATOR_ID,
    PACK_POLICIES,
    _build_case,
    _sample_definition,
    pack_case_paths,
    pack_root,
)
from aeread.shared_runner.run.resolver import case_content_sha256  # noqa: E402
from aeread.shared_runner.schemas import CaseManifest  # noqa: E402
import hashlib  # noqa: E402


@pytest.mark.parametrize("name", sorted(PACKS))
def test_pack_manifest_and_worlds_verify(name: str) -> None:
    manifest = json.loads((pack_root(name) / "pack.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    assert hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == manifest["manifest_sha256"]
    assert manifest["complete"] is True and manifest["admitted"] == 12
    assert manifest["generator_id"] == PACK_GENERATOR_ID
    assert manifest["seed_domain"]["start"] == PACKS[name]["seed_start"]
    assert all(row["verdict"] != "admit" for row in manifest["excluded"])
    assert 0 < manifest["admission_rate"] < 1
    paths = pack_case_paths(name)
    assert len(paths) == 12
    strata = {}
    for path, row in zip(paths, manifest["worlds"]):
        case = load_case(path)  # verifies the content digest
        assert case.case_id == row["case_id"] and case.content_sha256 == row["content_sha256"]
        assert case.payload["interaction"]["sample_noise"] == {"model": "binomial", "seed": row["world_seed"] + 500_000}
        assert case.payload["interaction"]["periods"]["count"] == 4
        assert case.split == PACKS[name]["split"]
        assert set(row["public_policies"]) == {*PACK_POLICIES, COMPETENT_BASELINE}
        policies = row["public_policies"]
        assert (
            policies[COMPETENT_BASELINE]["regret_to_upper_bound_usd"]
            < policies["defer"]["regret_to_upper_bound_usd"]
        )
        assert row["headroom_over_myopic"] >= 0.05 and row["headroom_over_loyal"] >= 0.05
        strata[row["stratum"]] = strata.get(row["stratum"], 0) + 1
    assert strata == {slug: 2 for slug in CASE_SLUGS}


def test_pack_domains_are_disjoint_and_worlds_regenerate_from_their_seed() -> None:
    domains = {name: range(spec["seed_start"], spec["seed_start"] + spec["scan_limit"]) for name, spec in PACKS.items()}
    names = sorted(domains)
    assert set(domains[names[0]]).isdisjoint(domains[names[1]])
    for name in names:
        manifest = json.loads((pack_root(name) / "pack.json").read_text(encoding="utf-8"))
        row = manifest["worlds"][0]
        rebuilt = _build_case(
            _sample_definition(row["stratum"], row["world_seed"]),
            screen=False,
            pack=name,
            split=PACKS[name]["split"],
            generator=(PACK_GENERATOR_ID, manifest["generator_version"]),
            sample_noise={"model": "binomial", "seed": row["world_seed"] + 500_000},
        )
        committed = json.loads((pack_root(name) / f"{row['slug']}.json").read_text(encoding="utf-8"))
        assert canonical_json_bytes(rebuilt) == canonical_json_bytes(committed)
        assert case_content_sha256(CaseManifest.from_dict(committed)) == row["content_sha256"]


def test_sampled_definitions_are_a_pure_function_of_the_seed() -> None:
    first = _sample_definition("loyalty_investment", 2420000)
    second = _sample_definition("loyalty_investment", 2420000)
    other = _sample_definition("loyalty_investment", 2420001)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first) != canonical_json_bytes(other)
    with pytest.raises(ValueError, match="unknown stratum"):
        _sample_definition("no_such_stratum", 1)


# --------------------------------------------------------------------------
# The competent observation-only baseline (P-D-07)
# --------------------------------------------------------------------------


def _greedy_period_decisions(payload):
    from aeread_families.procurement_allocation.headroom_screen import replay_baseline_outcome

    return replay_baseline_outcome(payload, "displayed_price_greedy")["period_decisions"]


@pytest.mark.parametrize("name", sorted(PACKS))
def test_deadline_aware_baseline_recomputes_and_wins_the_period_greedy_forfeits(name: str) -> None:
    from aeread_families.procurement_allocation.headroom_screen import replay_deadline_aware

    manifest = json.loads((pack_root(name) / "pack.json").read_text(encoding="utf-8"))
    for path, row in zip(pack_case_paths(name), manifest["worlds"]):
        if row["stratum"] != "retaliation_trap":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        outcome = replay_deadline_aware(payload)
        recorded = row["public_policies"][COMPETENT_BASELINE]
        assert outcome["regret_to_upper_bound_usd"] == pytest.approx(recorded["regret_to_upper_bound_usd"])
        # The pinned greedy rule spends period 1 qualifying every supplier and never
        # recovers once retaliation prices its padded order out of budget; the
        # deadline-aware rule awards in period 1 and keeps awarding.
        assert _greedy_period_decisions(payload) == ["defer"] * 4
        assert outcome["period_decisions"][0] == "award"
        assert outcome["periods_awarded"] == 4


def test_admission_rejects_a_world_no_competent_baseline_beats(monkeypatch) -> None:
    from aeread_families.procurement_allocation import relationship_case_matrix as matrix

    monkeypatch.setattr(matrix, "replay_deadline_aware", lambda payload: None)
    spec = {"seed_start": 2420000, "per_stratum": 1, "scan_limit": 6, "split": "dev"}
    built = matrix.build_pack("relationship_dev_v2", spec=spec)["manifest"]
    assert built["admitted"] == 0
    verdicts = {row["verdict"] for row in built["excluded"]}
    assert "reject: no competent observation-only baseline beats defer" in verdicts


# --------------------------------------------------------------------------
# Case cards for the analysis team
# --------------------------------------------------------------------------


def test_case_cards_are_fresh_and_agree_with_their_pack_manifests() -> None:
    from aeread_families.procurement_allocation import relationship_case_cards as cards

    assert cards.main(["--check"]) == 0, "regenerate: python -m aeread_families.procurement_allocation.relationship_case_cards"
    for pack in cards.PACKS:
        manifest = json.loads((pack_root(pack) / "pack.json").read_text(encoding="utf-8"))
        committed = json.loads((cards.CARDS_ROOT / f"{pack}.json").read_text(encoding="utf-8"))
        assert committed["pack_manifest_sha256"] == manifest["manifest_sha256"]
        for card, row in zip(committed["worlds"], manifest["worlds"]):
            assert card["content_sha256"] == row["content_sha256"]
            assert card["reference_solution"]["upper_bound_usd"] == pytest.approx(row["upper_bound_usd"])
            ladder = card["reference_ladder_regret_usd"]
            assert ladder["defer"] == pytest.approx(row["public_policies"]["defer"]["regret_to_upper_bound_usd"])
            assert ladder[COMPETENT_BASELINE] == pytest.approx(row["public_policies"][COMPETENT_BASELINE]["regret_to_upper_bound_usd"])
            assert [check["id"][:2] for check in card["diagnostic_checks"]] == ["D1", "D2", "D3", "D4", "D5", "D6"]
            assert set(card["buyer_sees"]) == set(card["hidden_from_buyer"])
