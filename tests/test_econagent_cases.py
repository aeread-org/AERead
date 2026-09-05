"""Tests for the econagent_v1 foundation stage: pins, importer, case records.

These tests exercise the real pinned upstream checkout on disk (read-only,
never executed for anything a plain file read can answer) and, where a
computed value is asserted, compare against upstream's own governing facts
(docs/econagent_adapter_spec.md) or against the kernel's own resolver
helpers -- never against a value this test suite invents.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.econagent_v1 import cases as econagent_cases


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    marker = root / "config.yaml"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent (mirroring tau3_retail's identical
            # convention) -- a bare module-level skip would otherwise make
            # pytest treat collection itself as an error in CI, where there
            # is no checkout.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


# ---------------------------------------------------------------------------
# Governing facts about the upstream corpus (spec section "Governing facts").
# ---------------------------------------------------------------------------


def test_profiles_json_is_four_sampling_pools_not_a_per_agent_roster() -> None:
    profiles = econagent_cases.load_upstream_profiles(UPSTREAM_ROOT)
    assert len(profiles["Age"]) == 200
    assert len(profiles["Name"]) == 160
    assert len(profiles["City"]) == 10

    bracket_keys = [key for key in profiles if "-" in key]
    assert len(bracket_keys) == 10
    for key in bracket_keys:
        assert len(profiles[key]) == 10


def test_config_yaml_declares_the_pinned_scenario_and_components() -> None:
    config_bytes = (UPSTREAM_ROOT / "config.yaml").read_bytes()
    assert b"scenario_name: one-step-economy" in config_bytes
    assert b"isoelastic_etas: [0.5, 0.5]" in config_bytes
    for component in (b"SimpleLabor", b"PeriodicBracketTax", b"SimpleConsumption", b"SimpleSaving"):
        assert component in config_bytes


def test_extract_bracket_schedule_reads_the_declared_tax_model() -> None:
    config_bytes = (UPSTREAM_ROOT / "config.yaml").read_bytes()
    assert (
        econagent_cases.extract_bracket_schedule(config_bytes)
        == econagent_cases.EXPECTED_BRACKET_SCHEDULE
    )


def test_extract_bracket_schedule_raises_when_absent() -> None:
    with pytest.raises(ValueError, match="tax_model"):
        econagent_cases.extract_bracket_schedule(b"env:\n  n_agents: 10\n")


# ---------------------------------------------------------------------------
# pins.json
# ---------------------------------------------------------------------------


def test_build_pins_facts() -> None:
    pins = econagent_cases.build_pins(UPSTREAM_ROOT)

    assert pins["upstream_repo"] == "tsinghua-fib-lab/ACL24-EconAgent"
    assert pins["upstream_commit"] == "bfada09"
    assert pins["bracket_schedule"] == "us-federal-single-filer-2018-scaled"
    assert pins["policy_model"] == "complex"

    for field in ("config_yaml_sha256", "profiles_json_sha256"):
        value = pins[field]
        assert isinstance(value, str) and len(value) == 64
        int(value, 16)  # must be valid hex

    assert pins["config_yaml_bytes"] == (UPSTREAM_ROOT / "config.yaml").stat().st_size
    assert pins["profiles_json_bytes"] == (
        UPSTREAM_ROOT / "data" / "profiles.json"
    ).stat().st_size

    # env_config_sha256 requires actually delegating to a bridge interpreter.
    # This environment is not required to have one, but whichever branch
    # fires must be internally consistent (never a silent fabricated hash).
    if pins["env_config_sha256"] is None:
        assert isinstance(pins["env_config_sha256_unavailable_reason"], str)
        assert pins["env_config_sha256_unavailable_reason"]
    else:
        assert "env_config_sha256_unavailable_reason" not in pins
        assert len(pins["env_config_sha256"]) == 64
        int(pins["env_config_sha256"], 16)


def test_env_config_sha256_reports_the_current_environment_honestly() -> None:
    """Documents, rather than hides, whether a bridge is importable here.

    If no pinned-upstream bridge interpreter is available,
    compute_env_config_sha256 must raise EconAgentBridgeNotAvailableError --
    never return a guessed value.
    """
    try:
        digest, env_config = econagent_cases.compute_env_config_sha256(UPSTREAM_ROOT)
    except econagent_cases.EconAgentBridgeNotAvailableError as exc:
        assert "bridge" in str(exc)
    else:
        assert isinstance(digest, str) and len(digest) == 64
        int(digest, 16)
        assert env_config["scenario_name"] == "one-step-economy"
        assert env_config["n_agents"] == 100  # unmodified base config value
        assert env_config["episode_length"] == 240


# ---------------------------------------------------------------------------
# Declared scenarios (spec section 1's table).
# ---------------------------------------------------------------------------


def test_pinned_scenarios_match_the_spec_table_exactly() -> None:
    by_id = {scenario["case_id"]: scenario for scenario in econagent_cases.SCENARIOS}
    assert set(by_id) == {
        "econagent.pilot.small10x12.seed0",
        "econagent.pilot.small10x12.seed1",
        "econagent.pilot.tiny4x6.seed0",
    }
    assert by_id["econagent.pilot.small10x12.seed0"]["n_agents"] == 10
    assert by_id["econagent.pilot.small10x12.seed0"]["episode_length"] == 12
    assert by_id["econagent.pilot.small10x12.seed0"]["world_seed"] == 0
    assert by_id["econagent.pilot.small10x12.seed1"]["world_seed"] == 1
    assert by_id["econagent.pilot.tiny4x6.seed0"]["n_agents"] == 4
    assert by_id["econagent.pilot.tiny4x6.seed0"]["episode_length"] == 6
    assert by_id["econagent.pilot.tiny4x6.seed0"]["world_seed"] == 0


def test_declared_not_run_scenario_is_the_full_paper_configuration() -> None:
    declared = econagent_cases.DECLARED_NOT_RUN_SCENARIO
    assert declared["scenario_id"] == "econagent.full.baseline100x240"
    assert declared["n_agents"] == 100
    assert declared["episode_length"] == 240
    assert declared["review_status"] == "not_run"
    run_case_ids = {scenario["case_id"] for scenario in econagent_cases.SCENARIOS}
    assert declared["scenario_id"] not in run_case_ids


def test_no_case_id_contains_a_colon() -> None:
    all_ids = [scenario["case_id"] for scenario in econagent_cases.SCENARIOS]
    all_ids.append(econagent_cases.DECLARED_NOT_RUN_SCENARIO["scenario_id"])
    for case_id in all_ids:
        assert ":" not in case_id


def test_n_agents_below_two_is_rejected_before_upstream_would_ever_see_it() -> None:
    # ai_economist.foundation.base.base_env.BaseEnvironment asserts
    # n_agents >= 2 (spec milestone-1 correction 7); the importer must refuse
    # a degenerate scenario before it is ever admitted into the corpus.
    pins = econagent_cases.build_pins(UPSTREAM_ROOT)
    bad_scenario = {
        "case_id": "econagent.pilot.degenerate1x1.seed0",
        "n_agents": 1,
        "episode_length": 1,
        "world_seed": 0,
        "purpose": "should never be admitted",
    }
    with pytest.raises(ValueError, match="n_agents"):
        econagent_cases.build_case(bad_scenario, pins)


# ---------------------------------------------------------------------------
# Case records (spec sections 1/3).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported() -> tuple[dict, dict[str, dict]]:
    return econagent_cases.import_all_cases(UPSTREAM_ROOT)


def test_case_ids_family_split_and_world_seed(imported) -> None:
    _pins, cases = imported
    assert set(cases) == {
        "econagent.pilot.small10x12.seed0",
        "econagent.pilot.small10x12.seed1",
        "econagent.pilot.tiny4x6.seed0",
    }
    for case_id, case in cases.items():
        assert case["case_id"] == case_id
        assert case["family_id"] == "econagent_v1"
        assert case["family_version"] == "0.1.0"
        assert case["split"] == "pilot"
        assert case["provenance"] == {
            "generator_id": "econagent_v1_importer",
            "generator_version": "0.1.0",
            "review_status": "upstream_pinned",
        }

    small0 = cases["econagent.pilot.small10x12.seed0"]
    assert small0["world_seed"] == 0
    assert len(small0["seats"]) == 10
    assert {seat["id"] for seat in small0["seats"]} == {f"agent_{i}" for i in range(10)}
    assert {seat["role"] for seat in small0["seats"]} == {"agent"}
    # One logical action per agent seat per month (milestone-3 correction --
    # the `agent_month` phase is `mode="simultaneous"` with all 10 seats
    # acting every month; see cases.py's `build_case` docstring comment).
    assert small0["episode"]["max_logical_actions"] == 10 * 12
    assert small0["episode"]["termination"] == ("episode_length_reached",)

    tiny0 = cases["econagent.pilot.tiny4x6.seed0"]
    assert tiny0["world_seed"] == 0  # same seed as small0, different shape -- allowed
    assert len(tiny0["seats"]) == 4
    assert tiny0["episode"]["max_logical_actions"] == 4 * 6


def test_case_record_round_trips_through_the_strict_r1_grammar(imported) -> None:
    _pins, cases = imported
    for case in cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(imported) -> None:
    _pins, cases = imported
    case = cases["econagent.pilot.small10x12.seed0"]
    assert case_content_sha256(case) == case["content_sha256"]

    # Mutating any part of the payload must change the digest -- guards
    # against a resolver/importer canonicalization bug silently accepting a
    # stale hash.
    mutated = copy.deepcopy(case)
    mutated["payload"]["scenario"]["beta"] = 999.0
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_scenario_id() -> None:
    # A naive "family:scenario" join is exactly what the kernel's identifier
    # grammar forbids (colons collapse GRPO groupings downstream); the
    # importer must mint dotted ids like "econagent.pilot.small10x12.seed0"
    # instead, never this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "econagent_v1:pilot:small10x12:seed0",
                "family_id": "econagent_v1",
                "family_version": "0.1.0",
                "split": "pilot",
                "world_seed": 0,
                "seats": [{"id": "agent_0", "role": "agent"}],
                "episode": {"max_logical_actions": 1, "termination": ["episode_length_reached"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "upstream_pinned",
                },
                "content_sha256": "0" * 64,
            }
        )


def test_import_all_cases_rejects_a_same_shape_world_seed_collision(monkeypatch) -> None:
    colliding_scenarios = (
        {
            "case_id": "econagent.pilot.collide.a",
            "n_agents": 4,
            "episode_length": 6,
            "world_seed": 0,
            "purpose": "a",
        },
        {
            "case_id": "econagent.pilot.collide.b",
            "n_agents": 4,
            "episode_length": 6,
            "world_seed": 0,
            "purpose": "b",
        },
    )
    monkeypatch.setattr(econagent_cases, "SCENARIOS", colliding_scenarios)
    with pytest.raises(ValueError, match="world_seed 0 is shared"):
        econagent_cases.import_all_cases(UPSTREAM_ROOT)


# ---------------------------------------------------------------------------
# Scenario manifest: the complete corpus enumeration, run and declared-not-run.
# ---------------------------------------------------------------------------


def test_scenario_manifest_has_three_run_and_one_declared_not_run(imported) -> None:
    _pins, cases = imported
    manifest = econagent_cases.build_scenario_manifest(cases)

    assert manifest["family_id"] == "econagent_v1"
    assert manifest["split"] == "pilot"
    assert len(manifest["scenarios"]) == 4

    run_scenarios = [s for s in manifest["scenarios"] if s["review_status"] != "not_run"]
    not_run_scenarios = [s for s in manifest["scenarios"] if s["review_status"] == "not_run"]
    assert len(run_scenarios) == 3
    assert len(not_run_scenarios) == 1

    declared = not_run_scenarios[0]
    assert declared["scenario_id"] == "econagent.full.baseline100x240"
    assert declared["n_agents"] == 100
    assert declared["episode_length"] == 240
    assert "case_id" not in declared  # never run, so no CaseManifest backs it

    for scenario in run_scenarios:
        assert scenario["case_id"] in cases
        assert scenario["content_sha256"] == cases[scenario["case_id"]]["content_sha256"]

    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)


def test_scenario_manifest_hash_changes_if_a_scenario_changes(imported) -> None:
    _pins, cases = imported
    manifest = econagent_cases.build_scenario_manifest(cases)
    mutated = copy.deepcopy(manifest)
    mutated["scenarios"][0]["purpose"] = "mutated"
    mutated_digest = econagent_cases._manifest_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


def test_build_scenario_manifest_raises_on_unresolved_scenario_case_id() -> None:
    with pytest.raises(ValueError, match="not found"):
        econagent_cases.build_scenario_manifest({})


# ---------------------------------------------------------------------------
# Import determinism.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    econagent_cases.run_import(UPSTREAM_ROOT, out_a)
    econagent_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 3 case files + pins.json + scenario_manifest.json
    assert len(files_a) == 5

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_three_case_files_plus_pins_and_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    econagent_cases.run_import(UPSTREAM_ROOT, out_dir)

    case_files = sorted(out_dir.glob("econagent.pilot.*.json"))
    assert len(case_files) == 3

    pins = json.loads((out_dir / "pins.json").read_text(encoding="utf-8"))
    assert pins["upstream_commit"] == "bfada09"

    manifest = json.loads((out_dir / "scenario_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["scenarios"]) == 4
