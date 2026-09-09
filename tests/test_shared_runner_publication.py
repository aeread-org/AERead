import hashlib
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
        "deferred_leaf_ids": ["leaf-2"],
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
        "deferred_leaf_ids": ["leaf-2"],
        "replay_level": "state_and_score",
        "evidence": {"root_sha256": "e" * 64},
        "failure": None,
        "scores": [{"leaf_id": "leaf-1", "value": 1.0}],
        "observability_limits": ["cost_lower_bound"],
        "scripted_seats": {},
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


# --- sanitized trajectory grain ---


def _housing_execution(tmp_path):
    import asyncio

    from aeread.shared_runner.task.execution import execute_plan_cell
    from aeread_families.housing.runner import (
        HousingScriptedLandlordProvider,
        HousingScriptedTenantProvider,
        build_housing_smoke,
        finalize_housing_execution,
    )

    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    return execution, receipt


FORBIDDEN_KEYS = {
    "observation", "input_text", "instructions", "messages", "output_text",
    "raw_response", "text", "state", "prompt", "reasoning",
}


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}/{key}", key
            yield from _walk(item, f"{path}/{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def test_sanitized_trajectory_rows_cover_every_logical_action_and_leak_nothing(tmp_path) -> None:
    from aeread.shared_runner.run.publication import (
        TRAJECTORY_ROW_SCHEMA_VERSION,
        sanitized_trajectory_jsonl,
        sanitized_trajectory_rows,
    )

    execution, receipt = _housing_execution(tmp_path)
    events = execution.evidence.read_events()
    logical_actions = [e for e in events if e.event_type == "logical_action_started"]
    rows = sanitized_trajectory_rows(execution.evidence, receipt)

    assert len(rows) == len(logical_actions) > 0
    assert [row["step_index"] for row in rows] == list(range(len(rows)))
    for row, started in zip(rows, logical_actions):
        assert row["schema_version"] == TRAJECTORY_ROW_SCHEMA_VERSION
        assert row["source_receipt_sha256"] == receipt.receipt_sha256
        assert row["run_plan_sha256"] == receipt.run_plan_sha256
        assert row["cell_id"] == receipt.cell_id
        assert row["episode_attempt_id"] == receipt.episode_attempt_id
        assert row["logical_action_id"] == started.logical_action_id
        assert row["seat_id"] and row["phase_id"] and row["profile_id"]
        assert row["attempts"], "every logical action has at least one attempt"
        attempt = row["attempts"][-1]
        assert attempt["provider_calls"], "an attempt records its provider calls"
        call = attempt["provider_calls"][0]
        assert {"provider_call_id", "resolved_model", "finish_reason", "input_tokens", "output_tokens", "cost_usd"} <= set(call)
        assert row["parse"]["ok"] in (True, False)
        assert "legal" in row["legality"]
        assert row["outcome"]["status"] in {"succeeded", "failed", "outcome_unknown"}
    leaked = sorted({key for _, key in _walk(list(rows)) if key in FORBIDDEN_KEYS})
    assert leaked == [], leaked

    payload = sanitized_trajectory_jsonl(rows)
    assert payload.count(b"\n") == len(rows)
    assert b'"raw_response"' not in payload and b'"output_text"' not in payload


def test_sanitized_trajectory_rows_reject_a_receipt_from_another_episode(tmp_path) -> None:
    from aeread.shared_runner.run.publication import sanitized_trajectory_rows

    execution, receipt = _housing_execution(tmp_path)
    # A durable receipt read from JSON is a plain mapping; alter its identity there,
    # since a typed EvaluationReceipt re-validates itself against its seal.
    other = json.loads(canonical_json_bytes(receipt))
    other["episode_attempt_id"] = "episode_attempt_elsewhere"
    with pytest.raises(ValueError, match="does not belong"):
        sanitized_trajectory_rows(execution.evidence, other)


def test_add_publication_artifact_updates_the_kernel_manifest_and_reseals(tmp_path) -> None:
    from aeread.shared_runner.run.publication import add_publication_artifact

    root = tmp_path / "bundle"
    root.mkdir()
    (root / "reports").mkdir()
    (root / "reports" / "summary.json").write_bytes(b'{"ok": true}\n')
    summary_sha = hashlib.sha256(b'{"ok": true}\n').hexdigest()
    core = {
        "schema_version": "aeread.publication_manifest/0.1",
        "campaign_id": "camp_v1",
        "publication_id": "camp_v1",
        "artifacts": {"reports/summary.json": summary_sha},
        "privacy_boundary": {"included": "x", "excluded": "y"},
        "source_bindings": {"plan_sha256": "a" * 64},
    }
    manifest = {**core, "manifest_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest()}
    (root / "publication_manifest.json").write_bytes(canonical_json_bytes(manifest) + b"\n")

    updated = add_publication_artifact(root, "trajectories/sanitized.jsonl", b'{"step_index": 0}\n')
    assert (root / "trajectories" / "sanitized.jsonl").read_bytes() == b'{"step_index": 0}\n'
    assert updated["artifacts"]["trajectories/sanitized.jsonl"] == hashlib.sha256(b'{"step_index": 0}\n').hexdigest()
    assert updated["artifacts"]["reports/summary.json"] == summary_sha
    recomputed = hashlib.sha256(canonical_json_bytes({k: v for k, v in updated.items() if k != "manifest_sha256"})).hexdigest()
    assert updated["manifest_sha256"] == recomputed != manifest["manifest_sha256"]
    on_disk = json.loads((root / "publication_manifest.json").read_text())
    assert on_disk == updated

    again = add_publication_artifact(root, "trajectories/sanitized.jsonl", b'{"step_index": 0}\n')
    assert again == updated
    with pytest.raises(ValueError, match="refusing to overwrite"):
        add_publication_artifact(root, "trajectories/sanitized.jsonl", b'{"step_index": 1}\n')

    (root / "publication_manifest.json").write_bytes(canonical_json_bytes({**manifest, "schema_version": "other/9.9"}) + b"\n")
    with pytest.raises(ValueError, match="schema"):
        add_publication_artifact(root, "trajectories/more.jsonl", b"{}\n")


def test_publish_trajectories_verb_is_registered_and_refuses_an_unpublished_receipt(tmp_path):
    from aeread.cli import VERBS
    from aeread.shared_runner.run.publish_trajectories import (
        GRAIN,
        publish_trajectory_grain,
    )

    assert VERBS["publish-trajectories"][0] == "aeread.shared_runner.run.publish_trajectories"

    execution, receipt = _housing_execution(tmp_path / "run")
    attempt_dir = execution.evidence.root
    bundle = tmp_path / "bundle"
    (bundle / "reports").mkdir(parents=True)
    (bundle / "publication_manifest.json").write_bytes(
        canonical_json_bytes(
            {"schema_version": "aeread.publication_manifest/0.1", "artifacts": {}, "manifest_sha256": ""}
        )
    )
    (bundle / "reports" / "summary.json").write_text(json.dumps({"receipts": []}))
    with pytest.raises(ValueError, match="not published"):
        publish_trajectory_grain(bundle, [attempt_dir])
    assert not (bundle / GRAIN).exists()

    (bundle / "reports" / "summary.json").write_text(
        json.dumps({"receipts": [receipt.receipt_sha256]})
    )
    count, manifest = publish_trajectory_grain(bundle, [attempt_dir])
    assert count > 0
    assert manifest["artifacts"][GRAIN] == hashlib.sha256((bundle / GRAIN).read_bytes()).hexdigest()


def test_sanitized_trajectory_rows_record_an_agent_action_failure_as_the_outcome():
    """A parse failure ends in logical_action_agent_action_failure, not _failed."""

    from types import SimpleNamespace

    from aeread.shared_runner.run.publication import sanitized_trajectory_rows

    ids = {"run_plan_id": "plan", "cell_id": "cell", "episode_id": "ep", "episode_attempt_id": "att"}
    events = [
        SimpleNamespace(
            event_type=kind, sequence=i, logical_action_id="la1", phase_instance_id="ph1",
            action_attempt_id=None, provider_call_id=None, tool_invocation_id=None,
            payload={"request": {"phase_id": "p", "seat_id": "s", "role": "r", "profile_id": "pr"}}
            if kind == "logical_action_started"
            else {"valid": False, "failure_code": "unknown_procurement_action"},
        )
        for i, kind in enumerate(["logical_action_started", "logical_action_agent_action_failure"])
    ]
    evidence = SimpleNamespace(
        verify_seal=lambda: SimpleNamespace(**ids),
        read_events=lambda: iter(events),
        read_event_payload=lambda event: event.payload,
    )
    (row,) = sanitized_trajectory_rows(evidence, {**ids, "receipt_sha256": "r", "run_plan_sha256": "p", "case_id": "c"})
    assert row["outcome"] == {
        "status": "agent_action_failure",
        "valid": False,
        "failure_code": "unknown_procurement_action",
    }
def _kernel_manifest_bundle(tmp_path):
    from aeread.shared_runner.run.publication import seal_publication_manifest

    bundle = tmp_path / "bundle"
    (bundle / "reports").mkdir(parents=True)
    (bundle / "README.md").write_text("# bundle\n")
    (bundle / "reports" / "summary.json").write_text(json.dumps({"rows": 3}))
    manifest = seal_publication_manifest(
        bundle,
        publication_id="bundle_v1",
        campaign_id="campaign_v1",
        privacy_boundary={"included": "facts", "excluded": "prompts"},
        source_bindings={"plan_sha256": "p" * 64},
        family_note="kept",
    )
    return bundle, manifest


def test_seal_publication_manifest_digests_every_file_and_seals_the_core(tmp_path):
    from aeread.shared_runner.run.publication import seal_publication_manifest

    bundle, manifest = _kernel_manifest_bundle(tmp_path)
    assert manifest["schema_version"] == "aeread.publication_manifest/0.1"
    assert set(manifest["artifacts"]) == {"README.md", "reports/summary.json"}
    for rel, digest in manifest["artifacts"].items():
        assert hashlib.sha256((bundle / rel).read_bytes()).hexdigest() == digest
    core = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    assert manifest["manifest_sha256"] == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    assert manifest["family_note"] == "kept"
    assert manifest["sanitization"]["raw_provider_responses_included"] is False
    on_disk = json.loads((bundle / "publication_manifest.json").read_bytes())
    assert on_disk == manifest
    with pytest.raises(ValueError, match="already exists"):
        seal_publication_manifest(bundle, publication_id="x", privacy_boundary={"included": "a", "excluded": "b"})
    with pytest.raises(ValueError, match="privacy_boundary"):
        seal_publication_manifest(tmp_path / "other", publication_id="x", privacy_boundary={"included": "a"})


def test_rebuild_publication_manifest_converts_list_rows_and_keeps_provenance(tmp_path):
    from aeread.shared_runner.run.publication import rebuild_publication_manifest

    bundle, manifest = _kernel_manifest_bundle(tmp_path)
    # Rewrite the manifest in the list layout some families produced.
    legacy = {k: v for k, v in manifest.items() if k not in ("artifacts", "manifest_sha256")}
    legacy["artifacts"] = [
        {"path": rel, "sha256": digest, "size_bytes": (bundle / rel).stat().st_size}
        for rel, digest in manifest["artifacts"].items()
    ]
    legacy["publication_sha256"] = "0" * 64
    (bundle / "publication_manifest.json").write_bytes(canonical_json_bytes(legacy))
    # A new grain appears before the rebuild.
    (bundle / "trajectories").mkdir()
    (bundle / "trajectories" / "sanitized.jsonl").write_text('{"a":1}\n')

    rebuilt = rebuild_publication_manifest(bundle)
    assert rebuilt["artifacts"] == {
        **manifest["artifacts"],
        "trajectories/sanitized.jsonl": hashlib.sha256(b'{"a":1}\n').hexdigest(),
    }
    assert "publication_sha256" not in rebuilt
    assert rebuilt["family_note"] == "kept"
    assert rebuilt["source_bindings"] == {"plan_sha256": "p" * 64}
    assert rebuilt == json.loads((bundle / "publication_manifest.json").read_bytes())
    assert rebuild_publication_manifest(bundle) == rebuilt  # idempotent


def test_rebuild_publication_manifest_refuses_changed_or_missing_recorded_files(tmp_path):
    from aeread.shared_runner.run.publication import rebuild_publication_manifest

    bundle, _ = _kernel_manifest_bundle(tmp_path)
    (bundle / "reports" / "summary.json").write_text(json.dumps({"rows": 4}))
    with pytest.raises(ValueError, match="differ from the recorded digest"):
        rebuild_publication_manifest(bundle)
    (bundle / "reports" / "summary.json").write_text(json.dumps({"rows": 3}))
    (bundle / "README.md").unlink()
    with pytest.raises(ValueError, match="missing from the bundle"):
        rebuild_publication_manifest(bundle)


def test_seal_manifest_verb_is_registered(tmp_path):
    from aeread.cli import VERBS
    from aeread.shared_runner.run.seal_manifest import main

    assert VERBS["seal-manifest"][0] == "aeread.shared_runner.run.seal_manifest"
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "README.md").write_text("x\n")
    assert main([str(bundle), "--new", "--included", "facts", "--excluded", "prompts"]) == 0
    assert main([str(bundle)]) == 0
    manifest = json.loads((bundle / "publication_manifest.json").read_bytes())
    assert manifest["publication_id"] == "b" and "README.md" in manifest["artifacts"]


def test_rebuild_publication_manifest_can_supply_a_missing_privacy_boundary_but_not_replace_one(tmp_path):
    from aeread.shared_runner.run.publication import rebuild_publication_manifest

    bundle, manifest = _kernel_manifest_bundle(tmp_path)
    stripped = {k: v for k, v in manifest.items() if k not in ("privacy_boundary", "manifest_sha256")}
    (bundle / "publication_manifest.json").write_bytes(canonical_json_bytes(stripped))
    boundary = {"included": "facts", "excluded": "prompts"}
    assert rebuild_publication_manifest(bundle, privacy_boundary=boundary)["privacy_boundary"] == boundary
    with pytest.raises(ValueError, match="different privacy_boundary"):
        rebuild_publication_manifest(bundle, privacy_boundary={"included": "other", "excluded": "prompts"})


def test_published_receipt_digests_scans_receipts_tables_and_the_manifest(tmp_path):
    from aeread.shared_runner.run.publish_trajectories import published_receipt_digests

    bundle = tmp_path / "b"
    for folder in ("reports", "receipts", "tables"):
        (bundle / folder).mkdir(parents=True)
    a, b, c, d = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    (bundle / "reports" / "summary.json").write_text(json.dumps({"receipt_sha256": a}))
    (bundle / "receipts" / "projections.jsonl").write_text(json.dumps({"source_receipt_sha256": b}) + "\n")
    (bundle / "tables" / "fact_manifest.json").write_text(json.dumps({"receipt": c}))
    (bundle / "publication_manifest.json").write_text(json.dumps({"source_receipt_sha256s": [d]}))
    assert published_receipt_digests(bundle) == {a, b, c, d}
