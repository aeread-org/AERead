"""Generator: AERead-authored govsim case corpus.

GovSim ships no discrete upstream task list (unlike tau2-bench's 114 JSON
records) -- only Hydra experiment YAML configs describing one canonical
starting condition per scenario. The case corpus here is therefore
procedurally *generated*, in the style of ``housing_v1``, not imported
per-task like ``tau3_retail``: every field in each case's ``payload`` is
either a pinned upstream constant (confirmed identical across all three
``*_baseline_concurrent.yaml`` configs during recon -- see
``docs/govsim_adapter_spec.md`` section 1) or an AERead authoring choice
(scenario x scripted-policy assignment, world seed). There is no per-task
upstream file to hash, so ``pins.json`` instead pins the exact upstream
source files this adapter executes (``concurrent_env.py``, one ``env.py``
per scenario, ``persona/common.py``) plus, when a bridge interpreter is
available, its resolved runtime dependency versions.

This module never reimplements upstream tool bodies, environment arithmetic,
or scenario prompt text (rule 2 of the adapter build, mirrored from
``tau3_retail``'s importer): the only upstream file bytes it ever touches
are the ones it hashes for ``pins.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import policies

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "govsim"
FAMILY_VERSION = "0.1.0"
SPLIT = "v1"
CASE_ID_PREFIX = "govsim"

# Kept in generator-review-status form (spec section 1): AERead authors and
# generates this corpus; nothing here is "upstream_pinned" the way a
# verbatim tau2 task record is.
VISIBILITY_POLICY = "govsim_symmetric_public_v1"

# Every reason this family's environment can terminate for, declared here
# next to the manifest that publishes it and enforced in `environment.py`'s
# `_set_termination`, mirroring `tau3_retail`'s identical discipline so the
# declaration and the behaviour cannot drift apart.
#
# `collapse_or_horizon` covers upstream's own single collapse test
# (`resource_in_pool < 5 or num_round >= max_num_rounds`, spec section 0):
# a collapsed episode is a valid, scoreable trial, not a distinct failure
# mode from reaching the round horizon (govsim_no_collapse, a separate
# diagnostic leaf, is what tells the two apart -- deferred to the
# measurement milestone). `operational_failure` covers a caught upstream
# assertion on a malformed action (QC Gate 2's "malformed-operational"
# golden) -- a typed, never-silent operational failure, never a scored zero.
TERMINATION_REASONS = ("collapse_or_horizon", "operational_failure")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "govsim"
UPSTREAM_COMMIT = "1d11adf047b24fa2ba0d44a1d4931015ea2e5210"

SCENARIOS: tuple[str, ...] = ("fishing", "sheep", "pollution")

# Confirmed by reading each scenario's env.py during recon (never by
# running it): the POOL_LOCATION override each *ConcurrentEnv subclass sets
# in its own __init__, distinct per scenario framing.
POOL_LOCATION_BY_SCENARIO: Mapping[str, str] = {
    "fishing": "lake",
    "sheep": "pasture",
    "pollution": "factory",
}

POLICIES: tuple[str, ...] = tuple(policies.SCRIPTED_POLICIES)

# One fixed seed for tonight's 9-cell corpus (spec section 1: "each one
# fixed world_seed"); a multi-seed expansion is a stated follow-up (spec
# section 6), not this milestone's job.
WORLD_SEED = 0

# Confirmed identical across all three scenarios' *_baseline_concurrent.yaml
# (spec section 0's "governing facts"); the five persona display names are
# the upstream-authored defaults for the same configs.
ENV_CFG: Mapping[str, Any] = {
    "num_agents": 5,
    "initial_resource_in_pool": 100,
    "max_num_rounds": 12,
    "harvesting_order": "concurrent",
    "assign_resource_strategy": "stochastic",
    "inject_universalization": False,
}
ENV_CFG_FIELDS: tuple[str, ...] = tuple(ENV_CFG)

# The pinned baseline `num_agents` (spec section 0's "governing facts") --
# every committed 9-cell corpus case uses this default, so its case_id
# grammar stays exactly as before (no suffix). Any OTHER num_agents (e.g.
# the QC Gate 2 degenerate-reference golden, num_agents=1) gets an explicit
# `.n{num_agents}` case_id suffix instead (see build_case's own docstring):
# `num_agents` changes seats, env_cfg, action budget, payload, and
# content_sha256, so two cases differing only in `num_agents` must never
# collide on the same case_id.
DEFAULT_NUM_AGENTS: int = ENV_CFG["num_agents"]

PERSONA_NAMES: tuple[str, ...] = ("John", "Kate", "Jack", "Emma", "Luke")


# --------------------------------------------------------------------------
# pins.json
# --------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scenario_env_path(upstream_root: Path, scenario: str) -> Path:
    return upstream_root / "simulation" / "scenarios" / scenario / "environment" / "env.py"


def _concurrent_env_path(upstream_root: Path) -> Path:
    return (
        upstream_root
        / "simulation"
        / "scenarios"
        / "common"
        / "environment"
        / "concurrent_env.py"
    )


def _persona_common_path(upstream_root: Path) -> Path:
    return upstream_root / "simulation" / "persona" / "common.py"


def build_pins(
    upstream_root: Path, *, bridge_versions: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Build the pin record (spec section 1).

    ``bridge_versions`` records the bridge interpreter's resolved
    ``numpy``/``pandas``/``omegaconf``/``pettingzoo`` versions (see
    ``GovsimBridge.runtime_info``) so a matching upstream commit checkout
    cannot silently hide a different dependency resolution. When no bridge
    interpreter was available at generation time, an explicit
    ``bridge_versions_unavailable_reason`` is recorded instead of a
    fabricated or omitted value -- mirroring ``tau3_retail``'s identical
    convention for ``tool_schema_sha256``.
    """
    pins: dict[str, Any] = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "concurrent_env_sha256": _sha256_file(_concurrent_env_path(upstream_root)),
        "persona_common_sha256": _sha256_file(_persona_common_path(upstream_root)),
        "scenario_env_sha256": {
            scenario: _sha256_file(_scenario_env_path(upstream_root, scenario))
            for scenario in SCENARIOS
        },
        "pool_location_by_scenario": dict(POOL_LOCATION_BY_SCENARIO),
    }
    if bridge_versions is not None:
        pins["bridge_versions"] = dict(bridge_versions)
    else:
        pins["bridge_versions_unavailable_reason"] = (
            "no bridge interpreter was available when pins.json was "
            "generated; set $AEREAD_GOVSIM_BRIDGE_PYTHON "
            "(tools/govsim_bridge/provision.sh) and regenerate to record "
            "numpy/pandas/omegaconf/pettingzoo versions"
        )
    return pins


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1).
# --------------------------------------------------------------------------


def build_case(
    scenario: str,
    policy_id: str,
    world_seed: int,
    *,
    num_agents: int = 5,
    split: str = SPLIT,
) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one scenario x policy x seed cell.

    ``num_agents`` defaults to the pinned baseline (5) but is overridable
    for the QC Gate 2 "degenerate-reference" golden (``num_agents=1``,
    spec section 4), which is deliberately never part of the committed
    9-cell corpus (``build_corpus``) below.

    ``num_agents`` changes seats, environment configuration, action
    budget, payload, and content hash, so it is also part of ``case_id``
    whenever it differs from ``DEFAULT_NUM_AGENTS`` -- otherwise
    ``fishing/sustainable_v1/seed=0`` built with 5 agents and again with 1
    agent would produce the same ``case_id`` for two semantically
    different manifests. The committed 9-cell corpus (always
    ``DEFAULT_NUM_AGENTS``) keeps its existing, unsuffixed ``case_id``
    grammar exactly as before.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    if policy_id not in policies.SCRIPTED_POLICIES:
        raise ValueError(
            f"unknown scripted policy {policy_id!r}; expected one of "
            f"{tuple(policies.SCRIPTED_POLICIES)}"
        )
    if not isinstance(num_agents, int) or isinstance(num_agents, bool):
        raise ValueError("num_agents must be an int")
    if not (1 <= num_agents <= len(PERSONA_NAMES)):
        raise ValueError(f"num_agents must be between 1 and {len(PERSONA_NAMES)}")

    persona_ids = [f"persona_{i}" for i in range(num_agents)]
    env_cfg = dict(ENV_CFG)
    env_cfg["num_agents"] = num_agents
    max_num_rounds = int(env_cfg["max_num_rounds"])
    # Total kernel-level logical actions over the whole episode: `harvest`
    # and `reflect` contribute one per persona per round, `discuss`
    # contributes one (persona_0 only) per round -- see environment.py's
    # `phases()` for the identical per-phase breakdown.
    max_logical_actions = (2 * num_agents + 1) * max_num_rounds

    case_id = f"{CASE_ID_PREFIX}.{scenario}.{policies.POLICY_ID_SHORT_NAME[policy_id]}.{world_seed}"
    if num_agents != DEFAULT_NUM_AGENTS:
        case_id = f"{case_id}.n{num_agents}"
    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": split,
        "world_seed": world_seed,
        "seats": [{"id": persona_id, "role": "persona"} for persona_id in persona_ids],
        "episode": {
            "max_logical_actions": max_logical_actions,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "upstream_repo": UPSTREAM_REPO,
            "upstream_commit": UPSTREAM_COMMIT,
            "scenario": scenario,
            "env_cfg": env_cfg,
            "personas": list(PERSONA_NAMES[:num_agents]),
            "policy_assignment": {
                persona_id: policy_id for persona_id in persona_ids
            },
            "world_seed": world_seed,
        },
        "provenance": {
            "generator_id": "govsim_case_generator",
            "generator_version": FAMILY_VERSION,
            "review_status": "generated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization
    # bugs early rather than at resolve time), mirroring tau3_retail.
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def build_corpus() -> dict[str, dict[str, Any]]:
    """Build all 9 case cells (spec section 1): 3 scenarios x 3 policies."""
    cases: dict[str, dict[str, Any]] = {}
    for scenario in SCENARIOS:
        for policy_id in POLICIES:
            case = build_case(scenario, policy_id, WORLD_SEED)
            if case["case_id"] in cases:
                raise ValueError(f"duplicate case_id: {case['case_id']!r}")
            cases[case["case_id"]] = case
    return cases


# --------------------------------------------------------------------------
# Corpus manifest (mirrors tau3_retail's pilot_manifest.json; here it
# indexes the whole 9-cell corpus rather than a subset, since govsim has no
# train/test split yet).
# --------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _corpus_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return _sha256_bytes(canonical_json_bytes(normalized))


def build_corpus_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "corpus_id": "govsim_v1",
        "family_id": FAMILY_ID,
        "split": SPLIT,
        "case_ids": sorted(cases),
        "content_sha256": "0" * 64,
    }
    digest = _corpus_content_sha256(data)
    data["content_sha256"] = digest
    return data


# --------------------------------------------------------------------------
# Disk I/O.
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(
    output_dir: Path,
    pins: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    corpus_manifest: Mapping[str, Any],
) -> None:
    """Write ``pins.json``, one file per case, and ``corpus_manifest.json``."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "corpus_manifest.json", corpus_manifest)


def run_import(
    upstream_root: Path,
    output_dir: Path,
    *,
    bridge_versions: Mapping[str, str] | None = None,
) -> None:
    """End-to-end: generate all 9 cells and write the corpus + pins.json."""
    pins = build_pins(upstream_root, bridge_versions=bridge_versions)
    cases = build_corpus()
    corpus_manifest = build_corpus_manifest(cases)
    write_cases(output_dir, pins, cases, corpus_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/govsim/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "govsim" / "v1"


def _fetch_bridge_versions(upstream_root: Path, bridge_python: str | None) -> dict[str, str] | None:
    if bridge_python is None:
        return None
    from .govsim_bridge import GovsimBridge

    bridge = GovsimBridge(python_executable=bridge_python, upstream_root=upstream_root)
    return bridge.runtime_info()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned govsim checkout (commit "
        "1d11adf047b24fa2ba0d44a1d4931015ea2e5210)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, the 9 case files, and "
        "corpus_manifest.json",
    )
    parser.add_argument(
        "--bridge-python",
        default=None,
        help="optional path to a provisioned bridge interpreter "
        "(tools/govsim_bridge/provision.sh); when given, pins.json records "
        "its resolved numpy/pandas/omegaconf/pettingzoo versions",
    )
    args = parser.parse_args(argv)
    bridge_versions = _fetch_bridge_versions(args.upstream_root, args.bridge_python)
    run_import(args.upstream_root, args.output_dir, bridge_versions=bridge_versions)


if __name__ == "__main__":
    main()
