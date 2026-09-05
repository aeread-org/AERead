"""Importer: pinned upstream EconAgent scenario configs -> AERead cases.

EconAgent (ACL 2024 main; arXiv 2310.10436; `tsinghua-fib-lab/ACL24-EconAgent`
pinned at commit ``bfada09``) has no per-task upstream corpus to enumerate --
unlike ``tau3_retail``'s 114 upstream task records, the "corpus" here is a
small, declared set of **scenario configurations**, each a deterministic
derivation of the pinned ``config.yaml``'s ``env`` block plus a
``world_seed``. See ``docs/econagent_adapter_spec.md`` section 1 for the
governing spec, and its "milestone 1 corrections" subsection for gaps found
while building this module.

This module never reimplements upstream engine mechanics, scripted-policy
formulas, or accounting rules (adapter rule 2). The one thing that requires
delegating to a *running* upstream-capable interpreter -- parsing
``config.yaml`` into the exact ``env`` sub-mapping passed to
``foundation.make_env_instance`` -- needs ``PyYAML``, which the project venv
does not carry (per ground rules, nothing may be installed into it). When no
bridge interpreter is available, that one field (``env_config_sha256``) is
left ``None`` with an explicit ``env_config_sha256_unavailable_reason``
rather than guessed at, mirroring ``tau3_retail/cases.py``'s identical
``tool_schema_sha256`` convention. Everything else here -- byte-exact file
hashes, and the tax-bracket schedule name, which is read directly out of the
raw ``config.yaml`` bytes via an anchored text search rather than a full YAML
parse -- needs no bridge at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1/3).
# --------------------------------------------------------------------------

FAMILY_ID = "econagent_v1"
FAMILY_VERSION = "0.1.0"
SPLIT = "pilot"

# Every reason this family's environment can terminate for, and nothing else
# (spec section 3: no error ceiling, no early-stop signal are declared for
# the scripted-only pass -- the episode always runs exactly
# ``episode_length`` months). Declared here, next to the manifest that
# publishes it, and enforced in ``environment.py``'s ``_set_termination`` so
# the declaration and the behaviour cannot drift apart.
TERMINATION_REASONS = ("episode_length_reached",)

VISIBILITY_POLICY = "econagent_v1_agent_private_v1"

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "tsinghua-fib-lab/ACL24-EconAgent"
UPSTREAM_COMMIT = "bfada09"

# The only wired policy this pass (spec section 6, "Scripted policy only").
POLICY_MODEL = "complex"

# Declared, upstream-controlled scripted-policy hyperparameters (spec section
# 4, "Successful" golden: "default beta=gamma=0.1, h=1"). Every pinned
# scenario in this pass uses these defaults; a case with different values
# would need its own explicit fields, not a silent override.
DEFAULT_BETA = 0.1
DEFAULT_GAMMA = 0.1
DEFAULT_H = 1.0

# Verbatim upstream constant, expected to match what a plain text search of
# config.yaml's PeriodicBracketTax component finds (see
# ``_extract_bracket_schedule``); never hand-derived independently of that
# check.
EXPECTED_BRACKET_SCHEDULE = "us-federal-single-filer-2018-scaled"

# --------------------------------------------------------------------------
# Pinned scenarios for this pass (spec section 1's table). Case ids obey the
# repo's identifier grammar -- lower-case, ``[a-z0-9_.-]``, no colons.
# --------------------------------------------------------------------------

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "econagent.pilot.small10x12.seed0",
        "n_agents": 10,
        "episode_length": 12,
        "world_seed": 0,
        "purpose": "primary parity + goldens target",
    },
    {
        "case_id": "econagent.pilot.small10x12.seed1",
        "n_agents": 10,
        "episode_length": 12,
        "world_seed": 1,
        "purpose": "second world seed, same shape",
    },
    {
        "case_id": "econagent.pilot.tiny4x6.seed0",
        "n_agents": 4,
        "episode_length": 6,
        "world_seed": 0,
        "purpose": "fast-running smoke/degenerate-edge case",
    },
)

# The full paper configuration is declared but never run this pass (spec
# section 1): recorded in the scenario manifest, not built as a
# ``CaseManifest`` -- ``ProvenanceSpec.review_status`` has no "not_run" value
# in the strict R1 grammar (``{"generated", "reviewed", "curated",
# "upstream_pinned"}``), and a real ``CaseManifest`` implies "this case runs",
# which is exactly the claim this scenario must not make.
DECLARED_NOT_RUN_SCENARIO: dict[str, Any] = {
    "scenario_id": "econagent.full.baseline100x240",
    "n_agents": 100,
    "episode_length": 240,
    "world_seed": None,
    "review_status": "not_run",
    "purpose": (
        "full paper configuration (100 agents x 240 months); declared for "
        "corpus-enumeration completeness, never executed or gated this pass"
    ),
}

SCENARIO_MANIFEST_ID = "econagent_v1_scenarios_v1"


class EconAgentBridgeNotAvailableError(RuntimeError):
    """No bridge interpreter could compute the resolved ``env`` sub-mapping.

    Raised only by :func:`compute_env_config_sha256`. Never caught silently
    with a fabricated hash -- callers decide whether a missing resolved-env
    digest is acceptable for their purpose.
    """


# --------------------------------------------------------------------------
# Upstream data access (plain file reads; no bridge required).
# --------------------------------------------------------------------------


def _upstream_config_path(upstream_root: Path) -> Path:
    return upstream_root / "config.yaml"


def _upstream_profiles_path(upstream_root: Path) -> Path:
    return upstream_root / "data" / "profiles.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return _sha256_bytes(data), len(data)


_TAX_MODEL_RE = re.compile(rb"tax_model:\s*([A-Za-z0-9_-]+)")


def extract_bracket_schedule(config_yaml_bytes: bytes) -> str:
    """Read the tax-bracket schedule name straight out of the raw bytes.

    A plain anchored text search, not a YAML parse -- this needs no bridge
    and reimplements nothing upstream: it only reads a literal string that
    already exists verbatim in ``config.yaml``. Raises if the declared field
    is missing or unparsable, rather than falling back to a hand-typed
    constant.
    """
    match = _TAX_MODEL_RE.search(config_yaml_bytes)
    if match is None:
        raise ValueError("config.yaml has no readable 'tax_model:' field")
    return match.group(1).decode("ascii")


def load_upstream_profiles(upstream_root: Path) -> dict[str, Any]:
    """Load the verbatim upstream sampling-pool dict (Age/Name/brackets/City)."""
    profiles_path = _upstream_profiles_path(upstream_root)
    with profiles_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------
# env_config_sha256: the one pin field that requires delegating to a bridge.
# --------------------------------------------------------------------------


def compute_env_config_sha256(upstream_root: Path) -> tuple[str, dict[str, Any]]:
    """Delegate to the bridge for the resolved ``env`` sub-mapping and its hash.

    Mirrors ``tau3_retail/cases.py``'s ``compute_tool_schema_sha256``: the
    schema/config *content* is never hand-derived, only ever produced by
    actually parsing the pinned ``config.yaml``. Returns
    ``(sha256_hex, env_config_dict)``.

    Raises:
        EconAgentBridgeNotAvailableError: if no bridge interpreter is
            available to parse ``config.yaml``.
    """
    # Imported lazily so importing ``cases`` never requires the bridge
    # client's own dependencies (none beyond the stdlib, but this keeps the
    # dependency direction explicit and matches the graceful-degradation
    # contract below).
    from .econagent_bridge import EconAgentBridge, EconAgentBridgeUnavailableError

    try:
        bridge = EconAgentBridge.discover(upstream_root)
        env_config = bridge.resolve_env_config()
    except EconAgentBridgeUnavailableError as exc:
        raise EconAgentBridgeNotAvailableError(
            "cannot compute env_config_sha256 by delegation: no pinned "
            f"upstream EconAgent bridge interpreter is available: {exc}"
        ) from exc
    digest = _sha256_bytes(canonical_json_bytes(env_config))
    return digest, env_config


# --------------------------------------------------------------------------
# pins.json
# --------------------------------------------------------------------------


def build_pins(upstream_root: Path, *, require_env_config: bool = False) -> dict[str, Any]:
    """Build the pin record (spec section 1).

    When ``require_env_config`` is False (the default) and no bridge
    interpreter is available, ``env_config_sha256`` is left ``None`` and
    ``env_config_sha256_unavailable_reason`` explains why, instead of
    raising -- so the rest of the importer (case records, which do not
    depend on this field) can still be produced and verified. Set
    ``require_env_config=True`` for a production build that must fail loudly
    if the digest cannot be computed.
    """
    config_path = _upstream_config_path(upstream_root)
    config_bytes = config_path.read_bytes()
    config_yaml_sha256 = _sha256_bytes(config_bytes)
    config_yaml_bytes = len(config_bytes)

    profiles_sha256, profiles_bytes = _sha256_file(_upstream_profiles_path(upstream_root))

    bracket_schedule = extract_bracket_schedule(config_bytes)
    if bracket_schedule != EXPECTED_BRACKET_SCHEDULE:
        raise ValueError(
            "config.yaml's tax_model does not match the expected schedule: "
            f"found {bracket_schedule!r}, expected {EXPECTED_BRACKET_SCHEDULE!r}"
        )

    env_config_sha256: str | None
    env_config_unavailable_reason: str | None
    try:
        env_config_sha256, _env_config = compute_env_config_sha256(upstream_root)
        env_config_unavailable_reason = None
    except EconAgentBridgeNotAvailableError as exc:
        if require_env_config:
            raise
        env_config_sha256 = None
        env_config_unavailable_reason = str(exc)

    pins: dict[str, Any] = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "config_yaml_sha256": config_yaml_sha256,
        "config_yaml_bytes": config_yaml_bytes,
        "profiles_json_sha256": profiles_sha256,
        "profiles_json_bytes": profiles_bytes,
        "bracket_schedule": bracket_schedule,
        "policy_model": POLICY_MODEL,
        "env_config_sha256": env_config_sha256,
    }
    if env_config_unavailable_reason is not None:
        pins["env_config_sha256_unavailable_reason"] = env_config_unavailable_reason
    return pins


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1/3).
# --------------------------------------------------------------------------


def build_case(scenario: Mapping[str, Any], pins: Mapping[str, Any]) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one declared, run scenario."""
    case_id = scenario["case_id"]
    n_agents = int(scenario["n_agents"])
    episode_length = int(scenario["episode_length"])
    world_seed = int(scenario["world_seed"])
    if n_agents < 2:
        # Matches ai_economist.foundation.base.base_env.BaseEnvironment's own
        # `assert n_agents >= 2` -- a scenario this adapter could never
        # actually construct upstream must not be admitted into the corpus
        # (spec milestone-1 correction 6).
        raise ValueError(f"{case_id!r} declares n_agents={n_agents}, but upstream requires >= 2")

    seats = [{"id": f"agent_{index}", "role": "agent"} for index in range(n_agents)]

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": world_seed,
        "seats": seats,
        "episode": {
            # Milestone-3 correction (found running the first real episode
            # through aeread.shared_runner.task.scheduler.run_episode): the
            # kernel counts one logical action per SEAT per phase instance,
            # not one per month -- the `agent_month` phase is
            # `mode="simultaneous"` with all `n_agents` seats acting every
            # month (see environment.py's `phases()`), so the true per-
            # episode ceiling is `n_agents * episode_length`, matching
            # `housing_v1`'s identical `num_tenants * rounds` convention for
            # its own simultaneous, self-looping phases
            # (src/aeread/shared_runner/housing.py). The literal
            # `episode_length` value used through milestones 1-2 was never
            # exercised against the real scheduler (every prior test called
            # `EconAgentV1Plugin`'s hooks directly) and undercounts by a
            # factor of `n_agents`, making every pinned scenario with
            # `n_agents > 1` fail before its first month with
            # `SchedulerContractError: case logical-action budget exceeded`.
            "max_logical_actions": n_agents * episode_length,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "scenario": {
                "case_id": case_id,
                "n_agents": n_agents,
                "episode_length": episode_length,
                "world_seed": world_seed,
                "beta": DEFAULT_BETA,
                "gamma": DEFAULT_GAMMA,
                "h": DEFAULT_H,
                "purpose": scenario["purpose"],
            },
            "pins": dict(pins),
        },
        "provenance": {
            "generator_id": "econagent_v1_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization bugs
    # early rather than at resolve time).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def import_all_cases(upstream_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Import every declared, run scenario into a case record.

    Returns ``(pins, {case_id: case_dict})`` in the declared scenario order.
    Gate 1's duplicate/near-duplicate and split-disjointness checks degrade,
    for this small a corpus, to: assert the case ids are distinct and assert
    no two scenarios of the *same shape* (``n_agents``, ``episode_length``)
    share a ``world_seed``. This is a milestone-1 correction to spec section
    1's literal "assert no two share a world_seed": the pinned table itself
    reuses ``world_seed=0`` across ``small10x12.seed0`` and
    ``tiny4x6.seed0``, which are different shapes entirely (10x12 vs 4x6) --
    a global uniqueness check would reject the very table it is meant to
    admit. Scoping the check to same-shape scenarios preserves the intent
    (catch a literally duplicated run) without rejecting two scenarios that
    happen to reuse a seed value across unrelated shapes.
    """
    pins = build_pins(upstream_root)
    cases: dict[str, dict[str, Any]] = {}
    seen_world_seeds: dict[tuple[int, int, int], str] = {}
    for scenario in SCENARIOS:
        case = build_case(scenario, pins)
        case_id = case["case_id"]
        if case_id in cases:
            raise ValueError(f"duplicate case_id: {case_id!r}")
        shape_seed_key = (scenario["n_agents"], scenario["episode_length"], case["world_seed"])
        if shape_seed_key in seen_world_seeds:
            raise ValueError(
                f"world_seed {case['world_seed']} is shared by "
                f"{seen_world_seeds[shape_seed_key]!r} and {case_id!r} at the same shape "
                f"(n_agents={scenario['n_agents']}, episode_length={scenario['episode_length']})"
            )
        seen_world_seeds[shape_seed_key] = case_id
        cases[case_id] = case
    return pins, cases


# --------------------------------------------------------------------------
# Scenario manifest: the complete corpus enumeration, run and declared-not-run.
# --------------------------------------------------------------------------


def build_scenario_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the full scenario enumeration, including the declared-not-run entry.

    This is the Gate-1 corpus-enumeration record: every scenario this family
    knows about, whether or not it is actually executed. Raises if any
    declared, run scenario id is missing from ``cases``.
    """
    missing = [scenario["case_id"] for scenario in SCENARIOS if scenario["case_id"] not in cases]
    if missing:
        raise ValueError(f"declared scenario case ids not found in imported corpus: {missing}")

    scenarios: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        case = cases[scenario["case_id"]]
        scenarios.append(
            {
                "scenario_id": scenario["case_id"],
                "case_id": scenario["case_id"],
                "n_agents": scenario["n_agents"],
                "episode_length": scenario["episode_length"],
                "world_seed": scenario["world_seed"],
                "review_status": "upstream_pinned",
                "purpose": scenario["purpose"],
                "content_sha256": case["content_sha256"],
            }
        )
    scenarios.append(dict(DECLARED_NOT_RUN_SCENARIO))

    data: dict[str, Any] = {
        "manifest_id": SCENARIO_MANIFEST_ID,
        "family_id": FAMILY_ID,
        "split": SPLIT,
        "scenarios": scenarios,
        "content_sha256": "0" * 64,
    }
    digest = _manifest_content_sha256(data)
    data["content_sha256"] = digest
    return data


def _manifest_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return _sha256_bytes(canonical_json_bytes(normalized))


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
    scenario_manifest: Mapping[str, Any],
) -> None:
    """Write ``pins.json``, one file per run scenario, and the scenario manifest."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "scenario_manifest.json", scenario_manifest)


def run_import(upstream_root: Path, output_dir: Path) -> None:
    """End-to-end: import all declared, run scenarios and write the case set."""
    pins, cases = import_all_cases(upstream_root)
    scenario_manifest = build_scenario_manifest(cases)
    write_cases(output_dir, pins, cases, scenario_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/econagent_v1/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "econagent_v1"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned EconAgent checkout (commit bfada09)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, the case files, and scenario_manifest.json",
    )
    args = parser.parse_args(argv)
    run_import(args.upstream_root, args.output_dir)


if __name__ == "__main__":
    main()
