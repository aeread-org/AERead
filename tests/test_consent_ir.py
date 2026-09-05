from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.consent_ir import (
    ConsentIRPlugin,
    buyer_gain,
    cycle_all_ir,
    family_manifest,
    ir_oracle,
    register_plugin,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "cases/consent_ir_v1/dev/visible_cycle_001.json"


def _case() -> CaseManifest:
    return CaseManifest.from_dict(json.loads(CASE_PATH.read_text()))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.plan_cell/0.1",
        cell_id="cell_consentir0000000001",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="consent_ir_dev_v1",
        suite_version="1.0.0",
        block_id="consent_ir_scripted",
        sampling_plan_id="consent_ir_fixed_v1",
        analysis_plan_id="consent_ir_analysis_v1",
        world_seed=case.world_seed,
        sampling_seed=73001,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_consent_ir_73001",
        cluster_level="world_seed",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="fixed_panel",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer"}),
        execution_mode="evaluate",
        case_max_logical_actions=1,
    )


def test_oracle_finds_exact_best_ir_cycle() -> None:
    values = _case().payload["values"]
    oracle = ir_oracle(values)
    assert oracle == {"max_buyer_gain": 8.0, "best_cycle": [0, 1, 2]}
    assert cycle_all_ir(oracle["best_cycle"], values)
    assert buyer_gain(oracle["best_cycle"], values) == 8.0


def test_registry_accepts_native_builtin() -> None:
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    assert registry.resolve_manifest(family_manifest()) is plugin


@pytest.mark.parametrize(
    ("response", "expected_cycle", "expected_ir", "expected_gain"),
    (
        ('{"cycle":[1,2]}', [0, 1, 2], True, 8.0),
        ('{"cycle":[1,3]}', [0, 1, 3], False, 0.0),
        ('{"cycle":[1,1]}', [0], False, 0.0),
        ('not json', [0], False, 0.0),
    ),
)
def test_real_scheduler_scores_valid_invalid_and_malformed_cycles(
    response: str,
    expected_cycle: list[int],
    expected_ir: bool,
    expected_gain: float,
) -> None:
    case = _case()
    plugin = ConsentIRPlugin()

    async def respond(_request):
        return CanonicalResponse(
            text=response,
            finish_reason="stop",
            empty=False,
            truncated=False,
            provider_call_ids=(),
            tool_invocation_ids=(),
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )

    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=plugin, response_source=respond)
    )
    assert result.outcome["cycle"] == tuple(expected_cycle)
    assert result.outcome["all_participant_ir"] is expected_ir
    assert result.outcome["buyer_gain"] == expected_gain

    scores = plugin.build_scorer(plugin.validate_payload(case.payload))(result.outcome)
    assert scores.primary_leaf_id == "consent_ir_buyer_gain_leaf"
    assert scores.scores[0].primary.value == expected_gain
    assert scores.scores[0].reference_values["exact_optimum"].value == 8.0
    assert scores.scores[1].primary.value == (1.0 if expected_ir else 0.0)


def test_payload_rejects_non_square_or_nonbeneficial_worlds() -> None:
    plugin = ConsentIRPlugin()
    with pytest.raises(ValueError, match="square"):
        plugin.validate_payload({"values": [[1, 2], [3]]})
    with pytest.raises(ValueError, match="beneficial"):
        plugin.validate_payload({"values": [[2, 1], [1, 2]]})
