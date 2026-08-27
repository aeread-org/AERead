"""Tests for the tau3.retail foundation stage: pins, importer, case records.

These tests exercise the real pinned upstream checkout on disk (read-only,
never executed for anything a plain file read can answer) and, where a
computed value is asserted, compare against upstream's own governing facts
(docs/tau3_retail_adapter_spec.md) or against the kernel's own resolver
helpers -- never against a value this test suite invents.
"""
from __future__ import annotations

import copy
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.tau3_retail import cases as tau3_cases


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_TAU2_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-tau2",
    )
    root = Path(candidate)
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream tau2-bench checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent. Without this flag pytest treats a
            # module-level skip as an error and the whole file fails to
            # collect -- which is what CI hit, since CI has no checkout.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

EXPECTED_DB_SHA256 = "413a65160adbdb5fde0ffc0015c49b6d70250b10c18128de169b597af7766765"
EXPECTED_DB_BYTES = 2811616
EXPECTED_DB_ONLY_IDS = {"33", "34"}


# ---------------------------------------------------------------------------
# Governing facts about the upstream corpus (spec section "Governing facts").
# ---------------------------------------------------------------------------


def test_upstream_task_corpus_has_114_tasks_ids_0_to_113() -> None:
    tasks = tau3_cases.load_upstream_tasks(UPSTREAM_ROOT)
    assert len(tasks) == 114
    ids = [task["id"] for task in tasks]
    assert ids == [str(n) for n in range(114)]


def test_upstream_task_corpus_initial_state_is_always_null() -> None:
    tasks = tau3_cases.load_upstream_tasks(UPSTREAM_ROOT)
    assert all(task["initial_state"] is None for task in tasks)


def test_reward_basis_distribution_matches_spec() -> None:
    tasks = tau3_cases.load_upstream_tasks(UPSTREAM_ROOT)
    distribution = Counter(
        tuple(sorted(task["evaluation_criteria"]["reward_basis"])) for task in tasks
    )
    assert distribution[("DB", "NL_ASSERTION")] == 112
    assert distribution[("DB",)] == 2
    db_only_ids = {
        task["id"]
        for task in tasks
        if tuple(sorted(task["evaluation_criteria"]["reward_basis"])) == ("DB",)
    }
    assert db_only_ids == EXPECTED_DB_ONLY_IDS


def test_nl_assertions_nonempty_count_is_40_and_differs_from_reward_basis() -> None:
    tasks = tau3_cases.load_upstream_tasks(UPSTREAM_ROOT)
    nonempty_ids = {
        task["id"]
        for task in tasks
        if task["evaluation_criteria"].get("nl_assertions")
    }
    assert len(nonempty_ids) == 40

    # The 72 tasks that declare NL_ASSERTION in reward_basis but carry no
    # actual assertions are a strict superset boundary: every reward_basis
    # NL_ASSERTION task minus the 40 "judge actually fires" tasks should be
    # exactly 72, and none of the 40 firing tasks should be DB-only.
    nl_reward_basis_ids = {
        task["id"]
        for task in tasks
        if "NL_ASSERTION" in task["evaluation_criteria"]["reward_basis"]
    }
    assert len(nl_reward_basis_ids) == 112
    assert nonempty_ids <= nl_reward_basis_ids
    assert len(nl_reward_basis_ids - nonempty_ids) == 72
    assert nonempty_ids.isdisjoint(EXPECTED_DB_ONLY_IDS)


def test_base_split_is_train_union_test_with_no_overlap() -> None:
    tasks = tau3_cases.load_upstream_tasks(UPSTREAM_ROOT)
    all_ids = {task["id"] for task in tasks}
    split = tau3_cases.load_upstream_split(UPSTREAM_ROOT)
    train_ids = set(split["train"])
    test_ids = set(split["test"])
    base_ids = set(split["base"])

    assert train_ids & test_ids == set()
    assert train_ids | test_ids == base_ids
    assert base_ids == all_ids
    assert len(train_ids) == 74
    assert len(test_ids) == 40
    assert len(base_ids) == 114


def test_db_json_hash_and_size_match_declared_pin() -> None:
    db_path = UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json"
    data = db_path.read_bytes()
    assert len(data) == EXPECTED_DB_BYTES
    import hashlib

    assert hashlib.sha256(data).hexdigest() == EXPECTED_DB_SHA256


# ---------------------------------------------------------------------------
# pins.json
# ---------------------------------------------------------------------------


def test_build_pins_facts() -> None:
    pins = tau3_cases.build_pins(UPSTREAM_ROOT)

    assert pins["upstream_repo"] == "tau2-bench"
    assert pins["upstream_commit"] == "fc0055dc4e0a316c3f83133267fbd6faaa770992"
    assert pins["db_sha256"] == EXPECTED_DB_SHA256
    assert pins["db_bytes"] == EXPECTED_DB_BYTES
    assert pins["greeting_message"] == "Hi! How can I help you today?"
    assert pins["max_steps"] == 100
    assert pins["judge_model"] == "gpt-4.1-2025-04-14"
    assert pins["judge_args"] == {"temperature": 0.0}
    assert pins["user_sim_model"] == "gpt-4.1-2025-04-14"
    assert pins["user_sim_args"] == {"temperature": 0.0}

    for field in ("tasks_sha256", "policy_sha256", "user_sim_guidelines_sha256"):
        value = pins[field]
        assert isinstance(value, str) and len(value) == 64
        int(value, 16)  # must be valid hex

    # tool_schema_sha256 requires actually importing the pinned upstream
    # package. This environment is not required to have it importable, but
    # whichever branch fires must be internally consistent (never a silent
    # fabricated hash).
    if pins["tool_schema_sha256"] is None:
        assert isinstance(pins["tool_schema_sha256_unavailable_reason"], str)
        assert pins["tool_schema_sha256_unavailable_reason"]
    else:
        assert "tool_schema_sha256_unavailable_reason" not in pins
        assert len(pins["tool_schema_sha256"]) == 64
        int(pins["tool_schema_sha256"], 16)


def test_tool_schema_sha256_reports_the_current_environment_honestly() -> None:
    """Documents, rather than hides, whether upstream is importable here.

    If the pinned upstream package's runtime dependencies (docstring_parser,
    loguru, deepdiff, python-dotenv, addict) are not installed,
    compute_tool_schema_sha256 must raise Tau2NotImportableError -- never
    return a guessed value.
    """
    try:
        digest = tau3_cases.compute_tool_schema_sha256(UPSTREAM_ROOT)
    except tau3_cases.Tau2NotImportableError as exc:
        assert "tau2" in str(exc)
    else:
        assert isinstance(digest, str) and len(digest) == 64
        int(digest, 16)


# ---------------------------------------------------------------------------
# Case records (spec section 3).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported() -> tuple[dict, dict[str, dict]]:
    return tau3_cases.import_all_cases(UPSTREAM_ROOT)


def test_case_id_family_and_world_seed_for_sample_tasks(imported) -> None:
    _pins, cases = imported
    for upstream_id, expected_case_id in (
        ("0", "tau3.retail.base.0"),
        ("33", "tau3.retail.base.33"),
        ("108", "tau3.retail.base.108"),
        ("113", "tau3.retail.base.113"),
    ):
        case = cases[expected_case_id]
        assert case["case_id"] == expected_case_id
        assert case["family_id"] == "tau3.retail"
        assert case["family_version"] == "0.1.0"
        assert case["split"] == "base"
        assert case["world_seed"] == int(upstream_id)
        assert case["upstream_task_id"] == upstream_id
        assert case["payload"]["task"]["id"] == upstream_id
        assert case["provenance"] == {
            "generator_id": "tau3_retail_importer",
            "generator_version": "0.1.0",
            "review_status": "upstream_pinned",
        }
        seat_ids = {seat["id"] for seat in case["seats"]}
        seat_roles = {seat["role"] for seat in case["seats"]}
        assert seat_ids == {"assistant", "user"}
        assert seat_roles == {"assistant", "user"}


def test_case_record_round_trips_through_the_strict_r1_grammar(imported) -> None:
    _pins, cases = imported
    for case in cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(imported) -> None:
    _pins, cases = imported
    case = cases["tau3.retail.base.14"]
    assert case_content_sha256(case) == case["content_sha256"]

    # Mutating any part of the payload must change the digest -- guards
    # against a resolver/importer canonicalization bug silently accepting a
    # stale hash.
    mutated = copy.deepcopy(case)
    mutated["payload"]["task"]["description"]["purpose"] = "mutated"
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_upstream_id() -> None:
    # Upstream ids are bare strings like "14" with no namespace of their own.
    # A naive "family:id" join (the obvious way to key a case by upstream id)
    # is exactly what the kernel's identifier grammar forbids (colons collapse
    # GRPO groupings downstream); the importer must mint "tau3.retail.base.14"
    # instead, never this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "tau3.retail:base:14",
                "family_id": "tau3.retail",
                "family_version": "0.1.0",
                "split": "base",
                "world_seed": 14,
                "seats": [{"id": "assistant", "role": "assistant"}],
                "episode": {"max_logical_actions": 1, "termination": ["error"]},
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


# ---------------------------------------------------------------------------
# Pilot manifest.
# ---------------------------------------------------------------------------


def test_all_18_pilot_ids_resolve(imported) -> None:
    _pins, cases = imported
    manifest = tau3_cases.build_pilot_manifest(cases)

    assert manifest["family_id"] == "tau3.retail"
    assert manifest["split"] == "base"
    assert len(manifest["case_ids"]) == 18
    assert len(set(manifest["case_ids"])) == 18
    assert manifest["upstream_task_ids"] == list(tau3_cases.PILOT_UPSTREAM_TASK_IDS)

    expected_upstream_ids = {
        "14", "53", "73", "108", "10", "11", "82", "83", "5", "48",
        "84", "91", "16", "28", "103", "104", "30", "46",
    }
    assert set(manifest["upstream_task_ids"]) == expected_upstream_ids

    for case_id, upstream_id in zip(manifest["case_ids"], manifest["upstream_task_ids"]):
        assert case_id in cases
        assert cases[case_id]["upstream_task_id"] == upstream_id

    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)


def test_pilot_manifest_hash_changes_if_the_id_list_changes(imported) -> None:
    _pins, cases = imported
    manifest = tau3_cases.build_pilot_manifest(cases)
    mutated = dict(manifest)
    mutated["case_ids"] = list(manifest["case_ids"][:-1]) + ["tau3.retail.base.0"]
    mutated_digest = tau3_cases._pilot_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


def test_build_pilot_manifest_raises_on_unresolved_pilot_id() -> None:
    with pytest.raises(ValueError, match="not found"):
        tau3_cases.build_pilot_manifest({})


# ---------------------------------------------------------------------------
# P1 -- import determinism: two importer runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    tau3_cases.run_import(UPSTREAM_ROOT, out_a)
    tau3_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 114 case files + pins.json + pilot_manifest.json
    assert len(files_a) == 116

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_114_case_files_plus_pins_and_pilot(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    tau3_cases.run_import(UPSTREAM_ROOT, out_dir)

    case_files = sorted(out_dir.glob("tau3.retail.base.*.json"))
    assert len(case_files) == 114

    pins = json.loads((out_dir / "pins.json").read_text(encoding="utf-8"))
    assert pins["db_bytes"] == EXPECTED_DB_BYTES

    pilot = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert len(pilot["case_ids"]) == 18
