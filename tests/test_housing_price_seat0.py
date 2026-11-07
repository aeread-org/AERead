"""The v15 seat-0 scorer (``price_seat0``): receipts that score the deciding tenant, built without editing runner.py.

What has to hold before a v15 identity freezes on it:

1. A scripted seat-0 policy run through the kernel under ``build_v15_setup`` seals an ``ok`` receipt whose primary is
   seat 0's measure-v2 net, equal to the same policy played offline, with the offline references; the receipt replays
   to the same scores.
2. At the holdout's rate, with the outside seats routed to the 0.3 provider, the same holds against the 0.3 market.
3. The plan names the new scorer and references and carries no v14 scorer pin; its registry holds the seat-0 plugin.
4. A terminal outcome without the seat-0 block, or with a realized net the market did not pay, is invalid.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.housing import price_campaign, price_pack_v2, price_reference, runner
from aeread_families.housing import price_outside_demand_holdout as holdout
from aeread_families.housing import price_seat0 as seat0

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "configs/housing_lemons_price_confirmatory_v14_glm53_flash_nextbit.json").read_text())
SEED = CONTRACT["world_seeds"][0]


def _run(arm: str, tmp: Path, *, holdout_rate: bool = False):
    setup = seat0.build_v15_setup(CONTRACT, arm, live=False, holdout_rate=holdout_rate)
    focal = runner.HousingScriptedTenantProvider()
    if holdout_rate:
        provider = price_campaign.SeatRouterClient(focal, holdout.HoldoutOutsideDemandProvider(), rival_block=CONTRACT["rivals"],
                                                   rewrite=holdout.rival_rewrite, log_path=tmp / "seat_calls.jsonl")
    else:
        provider = price_campaign.make_seat_router(price_campaign.identity(CONTRACT), CONTRACT, focal, tmp / "seat_calls.jsonl")
    cell = next(c for c in setup.plan.cells if c.world_seed == SEED and c.replicate_index == 0)
    execution = asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=tmp / "evidence",
        prompt_sources=setup.prompt_sources,
        providers={"housing_scripted_tenant": provider, "housing_scripted_landlord": runner.HousingScriptedLandlordProvider()},
        pricing=setup.pricing, harnesses=setup.harnesses))
    receipt = runner.finalize_housing_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = runner.replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=tmp / "evidence")
    return setup, execution, receipt, replayed


@pytest.mark.parametrize("arm", ["true_cost", "pooled"])
def test_the_receipt_scores_seat_zero_under_measure_v2_and_replays(arm: str, tmp_path: Path) -> None:
    setup, execution, receipt, replayed = _run(arm, tmp_path)
    assert receipt.status == "ok"
    assert canonical_json_bytes(replayed.scores) == canonical_json_bytes(receipt.scores)
    score = receipt.scores[0]
    rate = price_pack_v2.price_outside_demand.RATE
    assert score.primary.value == price_pack_v2.play(SEED, arm, "inspect_then_sign", rate)["primary_v2"]
    refs = seat0.references(SEED, arm, rate)
    assert score.reference_values["best_informed"].value == refs[seat0.BEST_INFORMED_REF]
    assert score.reference_values["optimum_upper_bound"].value == price_reference.ceiling(SEED, arm)
    assert execution.episode_result.outcome["seat0"]["net_realized"] == execution.episode_result.outcome["tenant_net_payoffs"]["tenant_0"]


def test_at_the_holdout_rate_the_receipt_scores_the_point_three_market(tmp_path: Path) -> None:
    _, _, receipt, replayed = _run("true_cost", tmp_path, holdout_rate=True)
    assert receipt.status == "ok"
    assert canonical_json_bytes(replayed.scores) == canonical_json_bytes(receipt.scores)
    assert receipt.scores[0].primary.value == price_pack_v2.play(SEED, "true_cost", "inspect_then_sign", holdout.RATE)["primary_v2"]


def test_the_plan_names_the_new_scorer_and_no_v14_scorer() -> None:
    setup = seat0.build_v15_setup(CONTRACT, "true_cost", live=False)
    family = setup.plan.families[0]
    assert family.scoring.scorer_id == seat0.SCORER_ID
    assert family.measurement.primary_estimand == seat0.ESTIMAND_ID
    kinds = {(p.component_id, p.kind) for p in setup.plan.implementation_pins}
    assert (seat0.SCORER_ID, "scorer") in kinds and ("housing_lemons_price_outcome_v1", "scorer") not in kinds
    assert isinstance(setup.registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1"), seat0.Seat0PricePlugin)


def test_an_outcome_without_the_seat_zero_block_or_with_a_wrong_net_is_invalid() -> None:
    setup = seat0.build_v15_setup(CONTRACT, "true_cost", live=False)
    case = setup.registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1").validate_payload(dict(setup.plan.cases[0].payload))
    assert seat0.score_seat0(case, {"valid": True}, 0.5).status == "invalid_measurement"
    bad = {"valid": True, "seat0": {"commit_decisions": [], "trajectory": {"inspections": [], "replies": []},
                                    "inspection_spend": 0.0, "net_realized": 12.0}}
    assert seat0.score_seat0(case, bad, 0.5).status == "invalid_measurement"
