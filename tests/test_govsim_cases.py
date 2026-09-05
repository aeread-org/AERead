"""Tests for the govsim foundation stage: pins, case generator, corpus.

Structural only -- no bridge needed (mirrors ``docs/govsim_adapter_spec.md``
section 5's test-plan classification). These tests read the pinned upstream
checkout's *files* (to hash them for ``pins.json``) but never import or
execute upstream code; they never need ``bridges/govsim-venv``.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest, is_exportable_id
from aeread_families.govsim import cases as govsim_cases
from aeread_families.govsim import policies


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_GOVSIM_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-govsim",
    )
    root = Path(candidate)
    marker = root / "simulation" / "scenarios" / "common" / "environment" / "concurrent_env.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream govsim checkout not found at {root}",
            # Every test in this module needs the checkout (pins.json hashes
            # its files); skipping the module keeps a missing checkout from
            # failing collection for the whole file, mirroring
            # test_tau3_retail_cases.py's identical convention.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


# ---------------------------------------------------------------------------
# pins.json (spec section 1).
# ---------------------------------------------------------------------------


def test_build_pins_without_a_bridge_records_an_explicit_unavailable_reason() -> None:
    pins = govsim_cases.build_pins(UPSTREAM_ROOT)
    assert pins["upstream_repo"] == "govsim"
    assert pins["upstream_commit"] == "1d11adf047b24fa2ba0d44a1d4931015ea2e5210"
    assert set(pins["scenario_env_sha256"]) == set(govsim_cases.SCENARIOS)
    for digest in (
        pins["concurrent_env_sha256"],
        pins["persona_common_sha256"],
        *pins["scenario_env_sha256"].values(),
    ):
        assert isinstance(digest, str) and len(digest) == 64
        int(digest, 16)
    assert "bridge_versions" not in pins
    assert isinstance(pins["bridge_versions_unavailable_reason"], str)
    assert pins["bridge_versions_unavailable_reason"]


def test_build_pins_records_supplied_bridge_versions() -> None:
    pins = govsim_cases.build_pins(
        UPSTREAM_ROOT, bridge_versions={"numpy_version": "1.24.4"}
    )
    assert pins["bridge_versions"] == {"numpy_version": "1.24.4"}
    assert "bridge_versions_unavailable_reason" not in pins


def test_pool_location_by_scenario_matches_governing_facts() -> None:
    assert govsim_cases.POOL_LOCATION_BY_SCENARIO == {
        "fishing": "lake",
        "sheep": "pasture",
        "pollution": "factory",
    }


# ---------------------------------------------------------------------------
# Case records (spec section 1).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> dict[str, dict]:
    return govsim_cases.build_corpus()


def test_corpus_has_exactly_9_cells_one_per_scenario_policy_pair(corpus) -> None:
    assert len(corpus) == 9
    seen = set()
    for scenario in govsim_cases.SCENARIOS:
        for policy_id in govsim_cases.POLICIES:
            seen.add((scenario, policy_id))
    assert len(seen) == 9


def test_case_id_matches_dot_joined_grammar_with_no_colon(corpus) -> None:
    for case_id in corpus:
        assert case_id.startswith("govsim.")
        assert ":" not in case_id
        assert is_exportable_id(case_id)
    assert "govsim.fishing.sustainable.0" in corpus
    assert "govsim.sheep.greedy.0" in corpus
    assert "govsim.pollution.mixed.0" in corpus


def test_case_fields_for_one_sample_cell(corpus) -> None:
    case = corpus["govsim.fishing.sustainable.0"]
    assert case["family_id"] == "govsim"
    assert case["family_version"] == "0.1.0"
    assert case["split"] == "v1"
    assert case["world_seed"] == 0
    assert case["upstream_task_id"] is None
    assert case["provenance"] == {
        "generator_id": "govsim_case_generator",
        "generator_version": "0.1.0",
        "review_status": "generated",
    }
    seat_ids = [seat["id"] for seat in case["seats"]]
    assert seat_ids == ["persona_0", "persona_1", "persona_2", "persona_3", "persona_4"]
    assert all(seat["role"] == "persona" for seat in case["seats"])
    assert tuple(case["episode"]["termination"]) == (
        "collapse_or_horizon",
        "operational_failure",
    )
    # harvest + reflect: 5 personas/round; discuss: 1/round; 12 rounds.
    assert case["episode"]["max_logical_actions"] == (2 * 5 + 1) * 12

    payload = case["payload"]
    assert payload["upstream_repo"] == "govsim"
    assert payload["upstream_commit"] == "1d11adf047b24fa2ba0d44a1d4931015ea2e5210"
    assert payload["scenario"] == "fishing"
    assert payload["env_cfg"] == {
        "num_agents": 5,
        "initial_resource_in_pool": 100,
        "max_num_rounds": 12,
        "harvesting_order": "concurrent",
        "assign_resource_strategy": "stochastic",
        "inject_universalization": False,
    }
    assert payload["personas"] == ["John", "Kate", "Jack", "Emma", "Luke"]
    assert payload["policy_assignment"] == {
        f"persona_{i}": "sustainable_v1" for i in range(5)
    }
    assert payload["world_seed"] == 0


def test_policy_assignment_is_uniform_across_personas_for_every_cell(corpus) -> None:
    for case_id, case in corpus.items():
        assignment = case["payload"]["policy_assignment"]
        assert len(set(assignment.values())) == 1, case_id


def test_case_record_round_trips_through_the_strict_grammar(corpus) -> None:
    for case in corpus.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(corpus) -> None:
    case = corpus["govsim.fishing.sustainable.0"]
    assert case_content_sha256(case) == case["content_sha256"]

    # Mutating any part of the payload must change the digest -- guards
    # against a canonicalization bug silently accepting a stale hash.
    mutated = copy.deepcopy(case)
    mutated["payload"]["world_seed"] = 999
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_build_case_rejects_unknown_scenario_or_policy() -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        govsim_cases.build_case("desert", "sustainable_v1", 0)
    with pytest.raises(ValueError, match="unknown scripted policy"):
        govsim_cases.build_case("fishing", "aggressive_v1", 0)


def test_build_case_degenerate_reference_golden_num_agents_1() -> None:
    # QC Gate 2's "degenerate-reference" golden (spec section 4): the
    # common-pool dilemma structurally vanishes with one agent. Never part
    # of the committed 9-cell corpus -- constructed ad hoc here and by the
    # environment tests that exercise it.
    case = govsim_cases.build_case("fishing", "sustainable_v1", 0, num_agents=1)
    # Closes triage Finding 6: a non-default num_agents is part of case_id,
    # never silently collapsed onto the 5-agent default's case_id (see
    # test_case_id_differs_for_different_num_agents_same_scenario_policy_seed
    # below for the direct collision proof).
    assert case["case_id"] == "govsim.fishing.sustainable.0.n1"
    assert [seat["id"] for seat in case["seats"]] == ["persona_0"]
    assert case["payload"]["env_cfg"]["num_agents"] == 1
    assert case["payload"]["personas"] == ["John"]
    assert case["episode"]["max_logical_actions"] == (2 * 1 + 1) * 12
    CaseManifest.from_dict(case)


def test_case_id_differs_for_different_num_agents_same_scenario_policy_seed() -> None:
    """Closes triage Finding 6: ``num_agents`` is explicitly configurable
    and changes seats, environment configuration, action budget, payload,
    and content hash -- ``case_id`` must never collapse two such
    semantically different manifests onto the same name. Before the fix,
    ``fishing/sustainable_v1/seed=0`` built with 5 agents and again with 1
    agent produced equal case IDs but unequal content hashes."""
    five_agents = govsim_cases.build_case("fishing", "sustainable_v1", 0, num_agents=5)
    one_agent = govsim_cases.build_case("fishing", "sustainable_v1", 0, num_agents=1)

    assert five_agents["case_id"] != one_agent["case_id"]
    assert five_agents["content_sha256"] != one_agent["content_sha256"]
    # The default (pinned baseline, matching the committed 9-cell corpus)
    # keeps its existing, unsuffixed case_id grammar exactly as before.
    assert five_agents["case_id"] == "govsim.fishing.sustainable.0"


def test_default_num_agents_case_id_is_unsuffixed_matching_the_committed_corpus() -> None:
    assert govsim_cases.DEFAULT_NUM_AGENTS == 5
    case = govsim_cases.build_case("fishing", "sustainable_v1", 0)
    assert case["case_id"] == "govsim.fishing.sustainable.0"


def test_build_case_rejects_out_of_range_num_agents() -> None:
    with pytest.raises(ValueError, match="num_agents"):
        govsim_cases.build_case("fishing", "sustainable_v1", 0, num_agents=0)
    with pytest.raises(ValueError, match="num_agents"):
        govsim_cases.build_case("fishing", "sustainable_v1", 0, num_agents=6)


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "govsim:fishing:sustainable:0",
                "family_id": "govsim",
                "family_version": "0.1.0",
                "split": "v1",
                "world_seed": 0,
                "seats": [{"id": "persona_0", "role": "persona"}],
                "episode": {"max_logical_actions": 1, "termination": ["error"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "generated",
                },
                "content_sha256": "0" * 64,
            }
        )


# ---------------------------------------------------------------------------
# Corpus manifest.
# ---------------------------------------------------------------------------


def test_corpus_manifest_lists_all_9_case_ids_sorted(corpus) -> None:
    manifest = govsim_cases.build_corpus_manifest(corpus)
    assert manifest["corpus_id"] == "govsim_v1"
    assert manifest["family_id"] == "govsim"
    assert manifest["case_ids"] == sorted(corpus)
    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)


def test_corpus_manifest_hash_changes_if_the_id_list_changes(corpus) -> None:
    manifest = govsim_cases.build_corpus_manifest(corpus)
    mutated = dict(manifest)
    mutated["case_ids"] = list(manifest["case_ids"]) + ["govsim.fishing.sustainable.1"]
    mutated_digest = govsim_cases._corpus_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


# ---------------------------------------------------------------------------
# Disk I/O / importer determinism (QC Gate 1: digest per task).
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    govsim_cases.run_import(UPSTREAM_ROOT, out_a)
    govsim_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 9 case files + pins.json + corpus_manifest.json
    assert len(files_a) == 11

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_9_case_files_plus_pins_and_corpus_manifest(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "run"
    govsim_cases.run_import(UPSTREAM_ROOT, out_dir)

    case_files = sorted(out_dir.glob("govsim.*.json"))
    assert len(case_files) == 9

    pins = json.loads((out_dir / "pins.json").read_text(encoding="utf-8"))
    assert pins["upstream_commit"] == "1d11adf047b24fa2ba0d44a1d4931015ea2e5210"

    corpus_manifest = json.loads(
        (out_dir / "corpus_manifest.json").read_text(encoding="utf-8")
    )
    assert len(corpus_manifest["case_ids"]) == 9


def test_committed_corpus_on_disk_matches_a_fresh_generation() -> None:
    """The committed ``cases/govsim/v1`` corpus is exactly what the
    generator produces today -- catches a hand-edited or stale committed
    file that the generator itself would no longer reproduce.
    """
    committed_dir = Path(__file__).resolve().parents[1] / "cases" / "govsim" / "v1"
    if not committed_dir.is_dir():
        pytest.skip("cases/govsim/v1 has not been generated yet")
    corpus = govsim_cases.build_corpus()
    for case_id, case in corpus.items():
        on_disk = json.loads((committed_dir / f"{case_id}.json").read_text(encoding="utf-8"))
        # Round-trip the freshly generated case through JSON too: tuple
        # fields (e.g. `episode.termination`) are lists once serialized,
        # and the committed file is what's on disk, not an in-memory dict.
        freshly_serialized = json.loads(json.dumps(case))
        assert on_disk == freshly_serialized, case_id
