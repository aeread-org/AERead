"""The supplier-judgment pack wired into the environment.

Played through the real plugin: what the buyer can see, what the opt-in
contract changes, and that the checks grade a reference buyer clean and a
rule-following buyer where the rule is wrong.
"""

from __future__ import annotations

import json
import re

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation import judgment_pack as jp
from aeread_families.procurement_allocation import supplier_profiles as sp
from aeread_families.procurement_allocation.environment import ProcurementAllocationPlugin

PACK = "judgment_dev_v1"
ROOT = jp.CASES_ROOT / PACK


def _manifest() -> dict:
    return json.loads((ROOT / "pack.json").read_text())


def _world(cell: str) -> tuple[dict, dict]:
    row = next(r for r in _manifest()["worlds"] if r["cell"] == cell and "twin_of" not in r)
    raw = json.loads((ROOT / f"{row['slug']}.json").read_text())
    return row, raw


class Episode:
    def __init__(self, payload: dict) -> None:
        self.plugin = ProcurementAllocationPlugin()
        self.case = self.plugin.validate_payload(payload)
        self.phase = self.plugin.phases(self.case)[0]
        self.state = self.plugin.initial_state(self.case, None)

    def observe(self) -> dict:
        return self.plugin.observe(self.case, self.state, "buyer", self.phase)

    def play(self, action: dict) -> None:
        parsed = self.plugin.parse_action(self.case, self.state, "buyer", self.phase, action)
        legality = self.plugin.legal(self.case, self.state, "buyer", self.phase, parsed.action) if parsed.ok else None
        envelope = ActionEnvelope("buyer", bool(parsed.ok and legality.legal), parsed.action if parsed.ok else None, parsed, legality)
        self.state = self.plugin.step(self.case, self.state, self.phase, {"buyer": envelope}).state

    def quote(self, supplier_id: str) -> str:
        self.play({"action": "request_quote", "supplier_id": supplier_id, "message": "quote"})
        return self.state["latest_offer_by_supplier"][supplier_id]

    def sample(self, supplier_id: str) -> int:
        self.play({"action": "request_sample", "supplier_id": supplier_id, "message": "sample"})
        reply = self.state["conversation"][-1]["content"]
        return int(re.match(r"Batch inspected: (\d+) defects", reply).group(1))

    def buy(self, controller: str, display: str) -> None:
        lines = [{"offer_id": self.quote(s), "quantity": jp.LOT_UNITS} for s in (controller, display)]
        self.play({"action": "submit_award", "award_lines": lines})


def _play(row: dict, raw: dict, choose) -> dict:
    """Run four periods; `choose(period, beliefs, sampled, after_sample)` returns
    ('sample'|'buy', role). Beliefs are updated exactly as grade() updates them."""
    ep = Episode(raw["payload"])
    roles = {"I": row["supplier_roles"]["incumbent"], "C": row["supplier_roles"]["challenger"]}
    controller = row["supplier_roles"]["controller"]
    for period in range(1, jp.PERIODS + 1):
        after = False
        while True:
            beliefs, sampled = _beliefs(row, ep)
            action, role = choose(period, beliefs, sampled, after)
            if action == "sample":
                ep.sample(roles[role])
                after = True
                continue
            ep.buy(controller, roles[role])
            break
    return ep.state


def _beliefs(row: dict, ep: Episode) -> tuple[dict, set]:
    b = {"I": row["posterior_bad"]["incumbent"], "C": row["posterior_bad"]["challenger"]}
    role = {row["supplier_roles"]["incumbent"]: "I", row["supplier_roles"]["challenger"]: "C"}
    t = sp.MARKET["type"]
    sampled = set()
    for entry in ep.state["conversation"]:
        c = str(entry.get("content", ""))
        if entry.get("role") == "supplier" and c.startswith("Batch inspected:") and entry["supplier_id"] in role:
            r = role[entry["supplier_id"]]
            d = int(re.match(r"Batch inspected: (\d+)", c).group(1))
            pb, pg = sp._pmf(jp.SAMPLE_UNITS, t["bad"]["defect_rate"])[d], sp._pmf(jp.SAMPLE_UNITS, t["good"]["defect_rate"])[d]
            b[r] = b[r] * pb / (b[r] * pb + (1 - b[r]) * pg)
            sampled.add(r)
    for h in ep.state["history"]:
        for dlv in h["delivery"]:
            if dlv["supplier_id"] not in role:
                continue
            r = role[dlv["supplier_id"]]
            if not dlv["on_time"]:
                pb, pg = 1 - t["bad"]["on_time"], 1 - t["good"]["on_time"]
            else:
                k = dlv["defective_units"]
                pb = t["bad"]["on_time"] * sp._pmf(jp.LOT_UNITS, t["bad"]["defect_rate"])[k]
                pg = t["good"]["on_time"] * sp._pmf(jp.LOT_UNITS, t["good"]["defect_rate"])[k]
            b[r] = b[r] * pb / (b[r] * pb + (1 - b[r]) * pg)
    return b, sampled


def _econ(row: dict, periods: int) -> sp.Economics:
    return sp.Economics(
        periods=periods, lot_units=jp.LOT_UNITS, sample_units=jp.SAMPLE_UNITS, sample_cost=row["sample_cost_usd"],
        values=tuple((k.split("_")[0], k.split("_")[1], v) for k, v in sorted(row["period_values_usd"].items())),
        lot_signal="delivery",
    )


def _reference_buyer(row: dict):
    def choose(period, b, sampled, after):
        q = sp._state_values(_econ(row, jp.PERIODS - period + 1), b["I"], b["C"], "I" in sampled, "C" in sampled, sp.MARKET, buy_only=after)
        best = max(q, key=q.get)
        return best.split("_")[0], best.split("_")[1]

    return choose


def test_the_buyer_sees_a_record_and_the_market_but_no_label() -> None:
    row, raw = _world("test_thin_record")
    obs = Episode(raw["payload"]).observe()
    assert obs["policy"]["award_requires"] == ["unexpired_formal_offer", "exact_variant"]
    assert "30%" in obs["policy"]["market_facts"]
    listings = {l["supplier_id"]: l["listing"] for l in obs["supplier_listings"]}
    for sid, listing in listings.items():
        assert re.fullmatch(r"(esp32_s3_n8r8|ssd1306_oled_096)_[a-z2-9]{4}", sid)
        assert "profile" in listing and "star_counts" in listing["profile"]
    display = [l for sid, l in listings.items() if sid.startswith("ssd1306")]
    strip = lambda l: {k: v for k, v in l.items() if k not in ("supplier_name", "displayed_unit_price_usd", "profile")}
    assert strip(display[0]) == strip(display[1])  # identical claims, only price and record differ
    text = json.dumps(obs).lower()
    for word in ("flaky", "reliable", "unproven", "known", "partner", "\"good\"", "\"bad\""):
        assert word not in text
    for cell in jp.CELLS:  # the product id is observed, so no cell name may appear anywhere
        assert cell not in text
    for sid, listing in listings.items():
        if sid.startswith("ssd1306"):
            assert listing["sample_terms"]["units"] == jp.SAMPLE_UNITS
    assert "late lot shows no defect count" in obs["policy"]["market_facts"]


def test_offer_states_the_common_commitment_and_the_check_reports_terms_only() -> None:
    row, raw = _world("stars_mislead")
    ep = Episode(raw["payload"])
    challenger = row["supplier_roles"]["challenger"]
    offer_id = ep.quote(challenger)
    assert ep.state["offers"][offer_id]["on_time_probability"] == jp.OFFER_ON_TIME
    controller_offer = ep.quote(row["supplier_roles"]["controller"])
    ep.play({"action": "check_award", "award_lines": [
        {"offer_id": controller_offer, "quantity": jp.LOT_UNITS}, {"offer_id": offer_id, "quantity": jp.LOT_UNITS}]})
    record = ep.state["award_checks"][-1]
    assert "completed_kits" not in record and "contribution_margin_usd" not in record
    assert "minimum_service_not_met" not in record["violations"]


def test_an_award_needs_no_sample_and_a_bad_lot_is_costly_not_rejected() -> None:
    row, raw = _world("stars_mislead")
    ep = Episode(raw["payload"])
    ep.buy(row["supplier_roles"]["controller"], row["supplier_roles"]["challenger"])
    result = ep.state["period_results"][0]
    assert result["decision"] == "award" and result["feasible"]
    kind = row["hidden_kind"]["challenger"]
    assert result["contribution_margin_usd"] == pytest.approx(row["period_values_usd"][f"C_{kind}"], abs=1e-6)


def test_period_values_match_the_environment() -> None:
    row, raw = _world("switch_on_record")
    values = jp.period_values(raw["payload"], {"I": row["supplier_roles"]["incumbent"], "C": row["supplier_roles"]["challenger"]})
    for (r, k), v in values.items():
        assert v == pytest.approx(row["period_values_usd"][f"{r}_{k}"], abs=1e-6)
    better = max(row["period_values_usd"][f"{r}_{row['hidden_kind']['incumbent' if r == 'I' else 'challenger']}"] for r in "IC")
    assert row["relationship_bound_usd"] == pytest.approx(jp.PERIODS * better, abs=1e-6)


@pytest.mark.parametrize("cell", sorted(jp.CELLS))
def test_a_buyer_that_follows_the_reference_grades_clean(cell: str) -> None:
    row, raw = _world(cell)
    state = _play(row, raw, _reference_buyer(row))
    graded = jp.grade(row, jp.decisions_from_state(state))
    assert graded["decision_regret_usd"] == pytest.approx(0.0, abs=1e-6)
    assert all(graded["checks"].values()), graded


def test_sampling_the_cheapest_everywhere_fails_where_testing_does_not_pay() -> None:
    row, raw = _world("not_worth_testing")

    def rule(period, b, sampled, after):
        if "C" not in sampled and not after:
            return "sample", "C"
        return "buy", "I" if b["C"] > 0.5 else "C"

    graded = jp.grade(row, jp.decisions_from_state(_play(row, raw, rule)))
    assert not graded["checks"]["J1"] and not graded["checks"]["J4"]
    assert graded["decision_regret_usd"] > jp.DECISION_TOLERANCE_USD


def test_committed_worlds_verify() -> None:
    from aeread.shared_runner.run.resolver import case_content_sha256
    from aeread.shared_runner.schemas import CaseManifest

    for row in _manifest()["worlds"]:
        raw = json.loads((ROOT / f"{row['slug']}.json").read_text())
        assert case_content_sha256(CaseManifest.from_dict(raw)) == row["content_sha256"] == raw["content_sha256"]
