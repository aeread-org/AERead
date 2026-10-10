"""The v14 confirmatory bundle: every planned cell, the declared analysis, a sealed manifest."""

from __future__ import annotations

import asyncio
import dataclasses
import json

from aeread.shared_runner.run.publication import PROHIBITED_PUBLIC_TEXT
from aeread_families.housing import price_campaign, price_publication

V14 = sorted(price_publication.V14_PANEL)


class _ScriptedFocal:
    async def complete(self, request):
        from aeread_families.housing.runner import HousingScriptedTenantProvider

        return await HousingScriptedTenantProvider().complete(dataclasses.replace(
            request, provider="housing_scripted_tenant",
            model="housing_scripted_tenant_inspect_then_sign_v1", revision="1.0.0"))


def test_bundle_holds_every_planned_cell_and_the_declared_analysis(tmp_path):
    paths, roots = [], []
    for campaign_id in V14:
        path = price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json")
        contract = price_campaign.load_contract(path)
        root = tmp_path / campaign_id
        # Two main-pack worlds and one holdout world run; every other planned cell is missing.
        asyncio.run(price_campaign.run(dict(contract, world_seeds=[300000, 300001, 400000]), root, live=True,
                                       provider=_ScriptedFocal()))
        paths.append(path)
        roots.append(root)
    manifest = price_publication.publish(paths, roots, tmp_path / "bundle")
    assert manifest["claim_status"] == "confirmatory"
    rows = [json.loads(line) for line in (tmp_path / "bundle/tables/cells.jsonl").read_text().splitlines()]
    assert len(rows) == 3 * 300 * 2
    done = [r for r in rows if r["status"] == "completed"]
    assert len(done) == 3 * 3 * 2 and {r["population"] for r in done} == {"main", "holdout"}
    assert all(r["status"] == "not_attempted" for r in rows if r["world_seed"] not in {300000, 300001, 400000})
    report = json.loads((tmp_path / "bundle/reports/analysis.json").read_text())
    assert report["declared"] == price_campaign.CONFIRMATORY_ANALYSIS
    assert set(report["models"]) == set(V14) and len(report["pairs"]) == 3
    # The scripted focal seat plays identically for every model, so every pair differs by zero.
    for pair in report["pairs"].values():
        assert pair["main"]["mean"] == 0.0
    text = b"".join(p.read_bytes() for p in (tmp_path / "bundle").rglob("*") if p.is_file()).decode().lower()
    assert not [token for token in PROHIBITED_PUBLIC_TEXT if token in text]


def test_holm_is_monotone_and_capped():
    adjusted = price_publication._holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == {"a": 0.03, "c": 0.06, "b": 0.06}
    assert price_publication._holm({"a": 0.6, "b": 0.7}) == {"a": 1.0, "b": 1.0}


def test_declared_fill_cells_are_exactly_v14_geminis_published_failures():
    from pathlib import Path

    rows = [json.loads(line) for line in Path("evidence/housing/housing_lemons_price_confirmatory_v14/tables/cells.jsonl").read_text().splitlines()]
    failed = {(r["world_seed"], r["arm"]) for r in rows
              if r["campaign_id"] == "housing_lemons_price_confirmatory_v14_gemini38_flash" and r["status"] != "completed"}
    assert failed == set(price_campaign.V14_GEMINI_REFUSED_CELLS) and len(failed) == 36


def test_fill_contract_differs_from_v14_gemini_only_where_declared():
    base = json.loads(price_campaign.DEFAULT_CONTRACT.with_name("housing_lemons_price_confirmatory_v14_gemini38_flash.json").read_text())
    fill = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{price_publication.FILL_ID}.json"))
    assert sorted(k for k in base if base[k] != fill[k]) == [
        "analysis", "campaign_id", "claim_status", "total_cost_ceiling_usd", "world_seeds"]
    assert fill["world_seeds"] == sorted({w for w, _ in price_campaign.V14_GEMINI_REFUSED_CELLS})
