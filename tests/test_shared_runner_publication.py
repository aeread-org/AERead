import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.run.publication import (
    PROHIBITED_PUBLIC_TEXT,
    SANITIZATION_DECLARATION,
    assert_public_payload,
    atomic_publish,
    jsonl,
    receipt_projection,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes


def test_prohibited_public_text_is_the_frozen_token_list() -> None:
    assert PROHIBITED_PUBLIC_TEXT == (
        '"raw_response"',
        '"failure_message"',
        '"output_text"',
        '"user_id"',
        "authorization:",
        "api_key",
        "/users/",
    )


def test_sanitization_declaration_names_every_excluded_class_as_false() -> None:
    assert SANITIZATION_DECLARATION == {
        "raw_provider_responses_included": False,
        "full_prompts_included": False,
        "model_reasoning_included": False,
        "complete_receipts_included": False,
        "failure_messages_included": False,
    }
    with pytest.raises(TypeError):
        SANITIZATION_DECLARATION["raw_provider_responses_included"] = True  # type: ignore[index]


def test_assert_public_payload_passes_clean_bytes_and_lists_every_match() -> None:
    assert_public_payload("summary.json", b'{"status": "ok"}')
    with pytest.raises(ValueError) as excinfo:
        assert_public_payload(
            "summary.json", b'{"RAW_RESPONSE": 1, "Authorization: Bearer x": 2}'
        )
    message = str(excinfo.value)
    assert message.startswith("summary.json contains prohibited public fields")
    assert '"raw_response"' in message and "authorization:" in message


def test_assert_public_payload_honours_a_custom_prohibited_list() -> None:
    assert_public_payload("x", b'"raw_response"', prohibited=("secret",))
    with pytest.raises(ValueError, match="prohibited"):
        assert_public_payload("x", b"has a SECRET", prohibited=("secret",))


def test_atomic_publish_writes_once_and_is_idempotent_for_identical_bytes(tmp_path: Path) -> None:
    path = tmp_path / "bundle" / "tables" / "rows.csv"
    atomic_publish(path, b"a,b\n1,2\n")
    assert path.read_bytes() == b"a,b\n1,2\n"
    atomic_publish(path, b"a,b\n1,2\n")
    assert path.read_bytes() == b"a,b\n1,2\n"
    assert [item.name for item in path.parent.iterdir()] == ["rows.csv"]


def test_atomic_publish_refuses_to_overwrite_different_bytes(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    atomic_publish(path, b"one")
    with pytest.raises(ValueError, match="refusing to overwrite different publication bytes"):
        atomic_publish(path, b"two")
    assert path.read_bytes() == b"one"


def test_atomic_publish_refuses_a_symlinked_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    with pytest.raises(ValueError, match="parent must not be a symlink"):
        atomic_publish(link / "rows.csv", b"x")


def test_jsonl_emits_one_canonical_line_per_row() -> None:
    rows = ({"b": 1, "a": 2}, {"z": None})
    assert jsonl(rows) == canonical_json_bytes(rows[0]) + b"\n" + canonical_json_bytes(rows[1]) + b"\n"
    assert jsonl(()) == b""


def _receipt(**overrides: object) -> dict:
    base = {
        "receipt_sha256": "r" * 64,
        "spec_version": "aeread.evaluation_receipt/1.0",
        "status": "ok",
        "inclusion_status": "included",
        "run_plan_id": "runplan_abc",
        "run_plan_sha256": "p" * 64,
        "cell_id": "cell-1",
        "case_id": "case-1",
        "case_sha256": "c" * 64,
        "episode_id": "ep-1",
        "episode_attempt_id": "att-1",
        "cluster_id": "cluster-1",
        "cluster_level": "case",
        "primary_leaf_id": "leaf-1",
        "replay_level": "state_and_score",
        "evidence": {"root_sha256": "e" * 64},
        "failure": None,
        "scores": [{"leaf_id": "leaf-1", "value": 1.0}],
        "observability_limits": ["cost_lower_bound"],
        "raw_response": "MUST NOT LEAK",
        "agent_profile_sha256_by_seat": {"analyst": "x"},
    }
    base.update(overrides)
    return base


def test_receipt_projection_whitelists_fields_and_binds_the_campaign_cell() -> None:
    projected = receipt_projection(_receipt(), campaign_cell_key="model__case__seed_1")
    assert projected == {
        "source_receipt_sha256": "r" * 64,
        "spec_version": "aeread.evaluation_receipt/1.0",
        "status": "ok",
        "inclusion_status": "included",
        "run_plan_id": "runplan_abc",
        "run_plan_sha256": "p" * 64,
        "cell_id": "cell-1",
        "case_id": "case-1",
        "case_sha256": "c" * 64,
        "episode_id": "ep-1",
        "episode_attempt_id": "att-1",
        "cluster_id": "cluster-1",
        "cluster_level": "case",
        "primary_leaf_id": "leaf-1",
        "replay_level": "state_and_score",
        "evidence": {"root_sha256": "e" * 64},
        "failure": None,
        "scores": [{"leaf_id": "leaf-1", "value": 1.0}],
        "observability_limits": ["cost_lower_bound"],
        "campaign_cell_key": "model__case__seed_1",
    }
    assert "raw_response" not in json.dumps(projected)


def test_receipt_projection_reduces_failure_to_its_typed_condition_and_class() -> None:
    receipt = _receipt(
        status="excluded",
        failure={
            "condition": "provider_contract",
            "failure_class": "empty_completion",
            "message": "verbatim provider text that must not leak",
        },
    )
    projected = receipt_projection(receipt, campaign_cell_key="k")
    assert projected["failure"] == {
        "condition": "provider_contract",
        "failure_class": "empty_completion",
    }


def test_receipt_projection_requires_every_whitelisted_field() -> None:
    receipt = _receipt()
    del receipt["primary_leaf_id"]
    with pytest.raises(KeyError):
        receipt_projection(receipt, campaign_cell_key="k")
