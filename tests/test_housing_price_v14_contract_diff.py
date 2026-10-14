"""Gate 4: the three v14 identities differ in exactly the declared fields, and nothing else (HL-J-12).

The treatment is the model profile, not the model alone: by contract the identities differ in
model and route, reasoning tier (GLM and Luna ``low``, Gemini ``minimal``), sampling (Luna takes
no temperature or top_p) and the run's cost ceiling. These tests load the three committed
contracts and build the six plans that ran (each plan's id must be the one the published bundle
records), flatten both, and assert the set of differing fields, so any other difference fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.housing import price_campaign
from aeread_families.housing import price_publication as pp

ROOT = Path(__file__).resolve().parents[1]
IDS = pp.V14_PANEL
CELLS = ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14/tables/cells.jsonl"

#: Contract fields that may differ between the three identities, by reason.
CONTRACT_DIFF = {
    "identity": {"campaign_id"},
    "model and route": {"route.route_id", "route.requested_model", "route.canonical_model", "route.provider",
                        "route.quantization", "route.input_per_million_usd", "route.cached_input_per_million_usd",
                        "route.output_per_million_usd"},
    "reasoning tier": {"controls.reasoning_effort"},
    "sampling": {"controls.temperature", "controls.top_p"},
    "cost ceiling": {"total_cost_ceiling_usd"},
}
#: Plan fields that may differ, after cells are put in world order and the identity's tenant
#: profile id is replaced by ``<tenant>``. Identifiers and digests derived from them are apart.
TENANT = "agent_profiles.<tenant>"
PLAN_DIFF = {
    "model and route": {f"{TENANT}.model.model", f"{TENANT}.model.revision", f"{TENANT}.harness.config.pricing_id",
                        f"{TENANT}.harness.config.pricing_sha256",
                        *(f"{TENANT}.harness.config.provider_metadata.{k}" for k in (
                            "canonical_model", "max_completion_price_per_million", "max_prompt_price_per_million",
                            "quantization", "route_provider"))},
    "reasoning tier": {f"{TENANT}.reasoning.effort"},
    "sampling": {f"{TENANT}.sampling.top_p", f"{TENANT}.harness.config.sampling_controls.temperature"},
}
DERIVED = re.compile(r"^(run_plan_id|plan_sha256|input_digests\..*|cells\[\d+\]\.cell_id"
                     r"|profile_admissions\.<tenant>\.admission_id)$")


def _flat(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flat(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            out.update(_flat(item, f"{prefix}[{index}]"))
        return out
    return {prefix: value}


def _differing(flats: list[dict[str, Any]]) -> set[str]:
    keys = set().union(*flats)
    return {k for k in keys if len({json.dumps(f.get(k, "<absent>"), sort_keys=True) for f in flats}) > 1}


def _contracts() -> list[dict[str, Any]]:
    return [price_campaign.load_contract(ROOT / f"configs/{cid}.json") for cid in IDS]


def test_the_contracts_differ_in_exactly_the_declared_fields() -> None:
    differing = _differing([_flat(c) for c in _contracts()])
    assert differing == set().union(*CONTRACT_DIFF.values())
    by_id = dict(zip(IDS, _contracts()))
    assert [by_id[cid]["controls"]["reasoning_effort"] for cid in IDS] == ["low", "low", "minimal"]
    assert [by_id[cid]["controls"]["temperature"] for cid in IDS] == [0.0, "unavailable", 0.0]
    assert [by_id[cid]["controls"]["top_p"] for cid in IDS] == [1.0, None, 1.0]
    assert [by_id[cid]["total_cost_ceiling_usd"] for cid in IDS] == [1.5, 1.5, 7.0]


def _plan(contract: dict[str, Any], arm: str) -> tuple[str, dict[str, Any]]:
    setup = price_campaign.build_setup(contract, arm, live=True)
    tenant = price_campaign.identity(contract)["profile"]
    payload = json.loads(canonical_json_bytes(setup.plan).decode("utf-8").replace(tenant, "<tenant>"))
    payload["cells"] = sorted(payload["cells"], key=lambda c: (c["world_seed"], c["replicate_index"]))
    payload["agent_profiles"] = {p["profile_id"]: p for p in payload["agent_profiles"]}
    payload["profile_admissions"] = {p["profile_id"]: p for p in payload["profile_admissions"]}
    return setup.plan.run_plan_id, payload


@pytest.fixture(scope="module")
def plans() -> dict[str, list[tuple[str, dict[str, Any]]]]:
    return {arm: [_plan(c, arm) for c in _contracts()] for arm in pp.ARMS}


def test_the_plans_built_are_the_plans_that_ran(plans) -> None:
    ran = {(r["campaign_id"], r["arm"]): r["run_plan_id"] for r in map(json.loads, CELLS.read_text().splitlines())
           if r.get("run_plan_id")}
    for arm, built in plans.items():
        for cid, (run_plan_id, _) in zip(IDS, built):
            assert run_plan_id == ran[(cid, arm)]


@pytest.mark.parametrize("arm", pp.ARMS)
def test_the_plans_differ_in_exactly_the_declared_fields(plans, arm) -> None:
    flats = [_flat(payload) for _, payload in plans[arm]]
    assert {k for k in _differing(flats) if not DERIVED.match(k)} == set().union(*PLAN_DIFF.values())
    luna = flats[IDS.index("housing_lemons_price_confirmatory_v14_gpt6_luna")]
    assert luna[f"{TENANT}.harness.config.sampling_controls.temperature"] == "unavailable"
    assert [f[f"{TENANT}.reasoning.effort"] for f in flats] == ["low", "low", "minimal"]


def test_the_check_fails_on_an_undeclared_difference(plans) -> None:
    # Counterexample: a different landlord budget in one plan is a difference nobody declared.
    flats = [_flat(payload) for _, payload in plans["true_cost"]]
    landlord = next(k for k in flats[0] if k.startswith("agent_profiles.housing_scripted_landlord") and k.endswith("max_cost_usd"))
    flats[1] = {**flats[1], landlord: 99.0}
    assert {k for k in _differing(flats) if not DERIVED.match(k)} != set().union(*PLAN_DIFF.values())
