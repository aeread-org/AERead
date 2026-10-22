"""v15's run and replay wiring (plan amendments 1, 3 and 4), with no provider called.

1. The A/A twin draws its own samples: its seed base is 88001 and its plans differ from the GLM confirmatory's; only a
   notice-5 identity may declare a seed base, so every earlier contract keeps 87001.
2. ``run`` plays a v15 contract's main pack and holdout as two streams through the seat-0 builder, the holdout's files
   prefixed, every receipt replayed; the replay factory finds both streams' plans.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from aeread_families.housing import price_campaign as pc
from aeread_families.housing import price_publication, price_seat0

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def _load(campaign_id: str) -> dict:
    return pc.load_contract(CONFIGS / f"{campaign_id}.json")


def test_the_aa_twin_draws_its_own_samples_and_only_notice_5_may_declare_a_seed_base() -> None:
    twin, glm = _load("housing_lemons_price_v15_glm53_flash_nextbit_aa"), _load("housing_lemons_price_v15_glm53_flash_nextbit")
    assert twin["controls"]["tenant_inference_seed_base"] == 88001 and glm["controls"]["tenant_inference_seed_base"] == 87001
    for arm in twin["arms"]:
        assert (price_seat0.build_v15_setup(twin, arm, live=True).plan.run_plan_id
                != price_seat0.build_v15_setup(glm, arm, live=True).plan.run_plan_id)
    assert {k: v for k, v in twin["controls"].items() if k != "tenant_inference_seed_base"} == \
        {k: v for k, v in glm["controls"].items() if k != "tenant_inference_seed_base"}
    with pytest.raises(ValueError, match="only a notice-5"):
        pc.seed_base({"notice_version": 4, "tenant_inference_seed_base": 1})
    assert pc.seed_base({"notice_version": 4}) == 87001


def test_run_plays_the_main_pack_and_the_holdout_as_two_streams(tmp_path: Path) -> None:
    contract = copy.deepcopy(_load("housing_lemons_price_v15_glm53_flash_nextbit"))
    main_seed, holdout_seed = contract["world_seeds"][0], contract["holdout"]["world_seeds"][0]
    contract["world_seeds"], contract["holdout"]["world_seeds"] = [main_seed], [holdout_seed]
    summary = asyncio.run(pc.run(contract, tmp_path, live=False))
    assert summary["planned_cells"] == 4 and summary["completed_cells"] == 4
    files = sorted(p.name for p in (tmp_path / "preflight").glob("*.json") if not p.name.startswith("summary"))
    assert files == sorted([f"world_{main_seed}__true_cost.json", f"world_{main_seed}__pooled.json",
                            f"holdout_world_{holdout_seed}__true_cost.json", f"holdout_world_{holdout_seed}__pooled.json"])
    rows = [json.loads((tmp_path / "preflight" / f).read_text()) for f in files]
    assert {r["stream"] for r in rows} == {"main", "holdout"}
    plans = {r["stream"]: set() for r in rows}
    for r in rows:
        plans[r["stream"]].add(r["run_plan_id"])
    assert not plans["main"] & plans["holdout"]


def test_the_replay_factory_finds_every_v15_plan() -> None:
    price_publication._SETUPS.clear()
    contract = _load("housing_lemons_price_v15_gpt6_luna")
    for holdout_rate in (False, True):
        for arm in contract["arms"]:
            run_plan_id = price_seat0.build_v15_setup(contract, arm, live=True, holdout_rate=holdout_rate).plan.run_plan_id
            assert price_publication.replay_setup({"run_plan_id": run_plan_id}).plan.run_plan_id == run_plan_id
    with pytest.raises(ValueError, match="no v14, v14 fill or v15 plan"):
        price_publication.replay_setup({"run_plan_id": "runplan_unknown"})
