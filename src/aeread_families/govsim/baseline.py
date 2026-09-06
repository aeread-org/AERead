"""Comparative reference values for govsim, produced rather than asserted.

govsim is a comparative family (`bound_status: baseline_only`), so three of
its five leaves are scored against `govsim_sustainable_v1` -- an
AERead-authored scripted policy, not an upstream number. Those reference
values have to come from somewhere; this module runs the declared policy
through the same environment, provider-free, and reports what it got.

Why produced and not pinned by hand: a baseline typed into a config is a
number nobody can check. Running the policy makes the reference reproducible
from the policy's own source, and the campaign freezes the result -- policy
id, policy digest, and the three values -- into its plan, so a reader can see
exactly what every comparative claim is measured against.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import run_episode

from .environment import GovsimPlugin, family_manifest
from .govsim_bridge import GovsimBridge
from .harness import ScriptedGovsimHarness
from .measurement import _vendored_gini

BASELINE_POLICY_ID = "govsim_sustainable_v1"
SCRIPTED_POLICY = "sustainable_v1"


def _cell(case: CaseManifest, seats: tuple[str, ...]) -> PlanCell:
    suffix = case.case_id.replace(".", "_")
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_govsim_baseline_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_govsim_baseline",
        suite_version="0.1.0",
        block_id="block_govsim_baseline",
        sampling_plan_id="sampling_govsim_baseline",
        analysis_plan_id="analysis_govsim_baseline",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_govsim_baseline_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {seat: BASELINE_POLICY_ID for seat in seats}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def policy_source_sha256() -> str:
    """Digest of the policy module the baseline was produced by."""
    return hashlib.sha256(
        (Path(__file__).with_name("policies.py")).read_bytes()
    ).hexdigest()


def compute_baseline(
    *, case: CaseManifest, upstream_root: Path, bridge: GovsimBridge
) -> dict[str, Any]:
    """Run `govsim_sustainable_v1` on one case and report its three values.

    Provider-free: every harvest comes from the scripted policy through the
    real scheduler, so the baseline traverses the same environment the live
    episodes do rather than a separate simulation that could drift from it.
    """
    plugin = GovsimPlugin(upstream_root=upstream_root, bridge=bridge)
    registry = PluginRegistry()
    registry.register_trusted(family_manifest(), plugin)
    family_case = plugin.validate_payload(case.payload)
    seats = tuple(seat.id for seat in case.seats)
    harness = ScriptedGovsimHarness(
        policy_assignment={seat: SCRIPTED_POLICY for seat in seats}
    )
    result = asyncio.run(
        run_episode(
            cell=_cell(case, seats),
            case=case,
            plugin=plugin,
            response_source=harness,
        )
    )
    terminal = result.terminal
    if terminal is None:
        raise ValueError(
            f"baseline episode for {case.case_id} did not reach a terminal"
        )
    collected = terminal["collected_resource"]
    values = np.array([float(v) for v in collected.values()], dtype=float)
    return {
        "policy_id": BASELINE_POLICY_ID,
        "scripted_policy": SCRIPTED_POLICY,
        "policy_source_sha256": policy_source_sha256(),
        "termination_reason": terminal["reason"],
        "survival_months": float(terminal["num_round"]),
        "total_harvest": float(sum(collected.values())),
        "gini": float(_vendored_gini(values)),
    }


def baselines_for_scoring(baseline: Mapping[str, Any]) -> dict[str, float]:
    """The three values `GovsimScorer` consumes, without the provenance."""
    return {
        "survival_months": float(baseline["survival_months"]),
        "total_harvest": float(baseline["total_harvest"]),
        "gini": float(baseline["gini"]),
    }


def baseline_digest(baseline: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(baseline))).hexdigest()


__all__ = [
    "BASELINE_POLICY_ID",
    "baseline_digest",
    "baselines_for_scoring",
    "compute_baseline",
    "policy_source_sha256",
]
