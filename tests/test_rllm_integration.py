"""Provider-free tests for the rLLM integration surface."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import re
import sys
import time
import types
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib landed in 3.11
    import tomli as tomllib

from aeread.integrations import rllm_dataset
from aeread.integrations.episode_core import (
    _configure_cache_environment,
    run_episode,
)
from aeread.integrations.failure_taxonomy import (
    EpisodeMeasurement,
    IntegrationConfigurationError,
    InvalidMeasurementError,
    RetryableInfrastructureError,
    failure_from_result,
)
from aeread.integrations.gateway_candidate import (
    EmptyModelResponse,
    GatewayCandidate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_REVISION = "1d1109a655e291b3001d8526d7c9ecc5b9328226"
EXPECTED_SPLIT_IDS = {
    "train": [
        "aeread.integration-v1.case01.s1200",
        "aeread.integration-v1.case01.s1201",
        "aeread.integration-v1.case01.s1202",
        "aeread.integration-v1.case01.s1203",
        "aeread.integration-v1.case02.s1200",
        "aeread.integration-v1.case02.s1201",
        "aeread.integration-v1.case02.s1202",
        "aeread.integration-v1.case02.s1203",
        "aeread.integration-v1.case03.s1200",
        "aeread.integration-v1.case03.s1201",
        "aeread.integration-v1.case03.s1202",
        "aeread.integration-v1.case03.s1203",
        "aeread.integration-v1.case04.s1200",
        "aeread.integration-v1.case04.s1201",
        "aeread.integration-v1.case04.s1202",
        "aeread.integration-v1.case04.s1203",
    ],
    "dev": [
        "aeread.integration-v1.case01.s2200",
        "aeread.integration-v1.case01.s2201",
        "aeread.integration-v1.case02.s2200",
        "aeread.integration-v1.case02.s2201",
        "aeread.integration-v1.case03.s2200",
        "aeread.integration-v1.case03.s2201",
        "aeread.integration-v1.case04.s2200",
        "aeread.integration-v1.case04.s2201",
    ],
    "test": [
        "aeread.integration-v1.case01.s2200",
        "aeread.integration-v1.case01.s2201",
        "aeread.integration-v1.case02.s2200",
        "aeread.integration-v1.case02.s2201",
        "aeread.integration-v1.case03.s2200",
        "aeread.integration-v1.case03.s2201",
        "aeread.integration-v1.case04.s2200",
        "aeread.integration-v1.case04.s2201",
    ],
}


def _response(content: str | None, response_id: str = "chatcmpl-test"):
    return SimpleNamespace(
        id=response_id,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


class _ScriptedClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.close_count = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        self.close_count += 1


def _successful_result(**updates):
    result = {
        "status": "ok",
        "aer": 0.25,
        "w_real": 2.5,
        "denominator": 10.0,
        "score": {},
        "turns": [
            {
                "phase": "proposal",
                "observation": "you are agent a1",
                "response": "PUBLIC ACTION\nPROPOSE 1 X",
                "response_id": "chatcmpl-one",
            }
        ],
        "candidate_request_count": 1,
        "blank_completion_count": 0,
        "completed_turn_count": 1,
    }
    result.update(updates)
    return result


# ---------------------------------------------------------------------------
# Measurement/failure taxonomy: no framework or provider required.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aer", "w_real"),
    [(0.25, 2.5), (0.0, 0.0), (-0.25, -2.5)],
    ids=["positive", "real-zero", "negative"],
)
def test_finite_measurements_preserve_raw_aer(aer, w_real):
    measurement = EpisodeMeasurement.from_result(
        _successful_result(aer=aer, w_real=w_real, denominator=10.0)
    )
    assert measurement.aer == aer
    assert measurement.w_real == w_real
    assert measurement.denominator == 10.0


def test_structured_provider_error_is_retryable_infrastructure():
    result = _successful_result(
        status="harness_error",
        aer=None,
        w_real=None,
        denominator=None,
        error="RateLimitError: provider returned 429",
        failure_class="retryable_infrastructure",
        retryable=True,
    )
    with pytest.raises(RetryableInfrastructureError) as caught:
        EpisodeMeasurement.from_result(result)
    assert caught.value.retryable is True
    assert caught.value.status == "harness_error"


def test_structured_blank_response_uses_existing_typed_exception():
    error = failure_from_result(
        {
            "status": "blank_response",
            "candidate_request_count": 1,
            "blank_completion_count": 1,
            "completed_turn_count": 0,
        }
    )
    assert isinstance(error, EmptyModelResponse)
    assert isinstance(error, RetryableInfrastructureError)


def test_degenerate_denominator_is_an_invalid_measurement():
    with pytest.raises(InvalidMeasurementError):
        EpisodeMeasurement.from_result(
            _successful_result(aer=None, w_real=1.0, denominator=0.0)
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_values_are_invalid_measurements(value):
    with pytest.raises(InvalidMeasurementError):
        EpisodeMeasurement.from_result(
            _successful_result(aer=value, w_real=value, denominator=10.0)
        )


def test_unknown_failure_status_fails_closed():
    with pytest.raises(IntegrationConfigurationError):
        EpisodeMeasurement.from_result(
            _successful_result(
                status="mystery_failure",
                aer=None,
                w_real=None,
                denominator=None,
            )
        )


def test_success_status_with_failure_metadata_fails_closed():
    with pytest.raises(IntegrationConfigurationError):
        EpisodeMeasurement.from_result(
            _successful_result(failure_class="unknown_failure_class")
        )


def test_nonboolean_retryability_fails_closed():
    error = failure_from_result(
        {
            "status": "provider_error",
            "failure_class": "retryable_infrastructure",
            "retryable": "false",
        }
    )
    assert isinstance(error, IntegrationConfigurationError)


# ---------------------------------------------------------------------------
# Versioned dataset membership, resources, and registration.
# ---------------------------------------------------------------------------


def test_manifest_split_membership_and_counts_are_an_exact_snapshot():
    splits = rllm_dataset.build_splits()
    assert {name: len(rows) for name, rows in splits.items()} == {
        "train": 16,
        "dev": 8,
        "test": 8,
    }
    assert {
        name: [row["id"] for row in rows]
        for name, rows in splits.items()
    } == EXPECTED_SPLIT_IDS
    assert splits["test"] == splits["dev"]


def test_manifest_names_only_the_four_public_case_families():
    manifest = rllm_dataset.load_manifest()
    assert manifest["scorer_version"] == "exchange-v1-d15-carveout-v2"
    assert [case["case_id"] for case in manifest["cases"]] == [
        "case01_visible_bilateral_ir",
        "case02_multiparty_clearing",
        "case03_hidden_discovery",
        "case04_consent_under_hidden_info",
    ]
    assert all("__panel_" not in case["case_resource"]
               for case in manifest["cases"])


def test_rows_have_the_versioned_portable_schema_and_unique_ids():
    splits = rllm_dataset.build_splits()
    canonical = splits["train"] + splits["dev"]
    assert len({row["id"] for row in canonical}) == 24
    assert set(canonical[0]) == {
        "id",
        "uid",
        "case_id",
        "case_resource",
        "case_sha256",
        "seed",
        "split",
        "caseset_version",
        "caseset_sha256",
        "protocol_version",
        "prompt_spec",
        "panel_spec",
        "scorer_version",
        "question",
    }
    assert all(row["uid"] == row["id"] for row in canonical)
    assert all(not Path(row["case_resource"]).is_absolute()
               for row in canonical)
    assert canonical[4] == {
        "id": "aeread.integration-v1.case02.s1200",
        "uid": "aeread.integration-v1.case02.s1200",
        "case_id": "case02_multiparty_clearing",
        "case_resource": (
            "exchange_economy/cases_v0/"
            "case02_multiparty_clearing.json"
        ),
        "case_sha256": (
            "503a74a6c332c04b647cc33990b3ad3ed43f23674bbdd40f132885816b168a28"
        ),
        "seed": 1200,
        "split": "train",
        "caseset_version": "integration-v1",
        "caseset_sha256": (
            "4124ea21744ee44109687dc90ed93806a96a70fb22788bd774553ef9fbf243a4"
        ),
        "protocol_version": "exchange-v1",
        "prompt_spec": {
            "source": "aeread.exchange_v1_runner",
            "sha256": (
                "b95630b7f9b17822a24a7822d9483de549463e34e2299c66d78b9607271ff352"
            ),
        },
        "panel_spec": {
            "source": "ordered case external-scoring role specifications",
            "sha256": (
                "02884e8bd1588eed59f75708e0e0b3ebd5e43a85a40c8f22fc4bb9d7d3a6e496"
            ),
        },
        "scorer_version": "exchange-v1-d15-carveout-v2",
        "question": "AERead exchange-economy case02, seed 1200",
    }


def test_case_resources_resolve_and_verify_without_using_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    rows = rllm_dataset.build_rows("train")
    assert all(rllm_dataset.resolve_case_resource(row).is_file()
               for row in rows)


def test_modified_case_resource_fails_hash_check_before_episode_run(
    tmp_path, monkeypatch
):
    from aeread.integrations import rllm_flow

    row = rllm_dataset.build_rows("train")[0]
    source = rllm_dataset.resolve_case_resource(row)
    modified = tmp_path / row["case_resource"]
    modified.parent.mkdir(parents=True)
    modified.write_bytes(source.read_bytes() + b"\n")
    monkeypatch.setattr(
        rllm_dataset, "_case_resource_roots", lambda: [tmp_path]
    )
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        return _successful_result()

    monkeypatch.setattr(rllm_flow, "run_episode", fake_run)
    config = SimpleNamespace(
        base_url="http://x/v1",
        model="m",
        sampling_params={},
        metadata={},
        is_validation=False,
    )
    with pytest.raises(rllm_dataset.CaseIntegrityError) as caught:
        rllm_flow._build_measured_episode(row, config)
    assert "hash mismatch" in str(caught.value)
    assert called is False


def test_same_manifest_row_rebuilds_the_same_prepared_case(tmp_path):
    from aeread import exchange_v1_pilot as pilot

    first_row = rllm_dataset.build_rows("train")[6]
    second_row = rllm_dataset.build_rows("train")[6]
    assert first_row == second_row
    case_path = rllm_dataset.resolve_case_resource(first_row)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = pilot.seeded_case(
        case_path, first_row["seed"], first_dir, "rllm"
    )
    second = pilot.seeded_case(
        case_path, second_row["seed"], second_dir, "rllm"
    )
    assert first.read_bytes() == second.read_bytes()


def test_registration_from_noncheckout_cwd_registers_all_public_splits(
    tmp_path, monkeypatch
):
    calls: list[tuple[str, list[dict], str, dict]] = []

    class Registry:
        @classmethod
        def register_dataset(cls, name, rows, split, **metadata):
            calls.append((name, rows, split, metadata))

    rllm_module = types.ModuleType("rllm")
    rllm_module.__path__ = []
    data_module = types.ModuleType("rllm.data")
    data_module.DatasetRegistry = Registry
    monkeypatch.setitem(sys.modules, "rllm", rllm_module)
    monkeypatch.setitem(sys.modules, "rllm.data", data_module)
    monkeypatch.chdir(tmp_path)

    counts = rllm_dataset.register()

    assert counts == {"train": 16, "dev": 8, "test": 8}
    assert [(name, split, len(rows)) for name, rows, split, _ in calls] == [
        ("aeread", "train", 16),
        ("aeread", "dev", 8),
        ("aeread", "test", 8),
    ]
    assert calls[2][1] == calls[1][1]
    assert "public-development alias" in calls[0][3]["description"]


def test_wheel_force_includes_manifest_and_case_resource_tree():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    included = project["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert included["configs"] == "aeread/configs"
    assert included[
        "src/aeread/integrations/rllm_caseset_integration_v1.json"
    ] == "aeread/integrations/rllm_caseset_integration_v1.json"


# ---------------------------------------------------------------------------
# Candidate client: one request, no SDK retry, typed blanks, clean lifecycle.
# ---------------------------------------------------------------------------


def test_gateway_client_disables_sdk_retries_and_sets_timeout(monkeypatch):
    captured: dict = {}
    fake = _ScriptedClient([_response("NO_ACTION")])

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return fake

    import openai

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    with GatewayCandidate("http://gateway/v1", "policy", timeout=17.5) as candidate:
        assert candidate.act("observation", "proposal") == "NO_ACTION"

    assert captured["max_retries"] == 0
    assert captured["timeout"] == 17.5
    assert fake.close_count == 1


def test_whitespace_completion_raises_before_a_turn_is_recorded():
    client = _ScriptedClient([_response("   \n")])
    candidate = GatewayCandidate(
        "http://gateway/v1", "policy", client=client, sampling_params={}
    )

    with pytest.raises(EmptyModelResponse) as caught:
        candidate.act("observation", "proposal")

    assert len(client.requests) == 1
    assert candidate.turns == []
    assert candidate.candidate_request_count == 1
    assert candidate.blank_completion_count == 1
    assert caught.value.completed_turn_count == 0


def test_missing_completion_is_a_typed_blank_without_an_internal_retry():
    client = _ScriptedClient([SimpleNamespace(id="empty", choices=[])])
    candidate = GatewayCandidate(
        "http://gateway/v1", "policy", client=client, sampling_params={}
    )
    with pytest.raises(EmptyModelResponse):
        candidate.act("observation", "proposal")
    assert len(client.requests) == 1
    assert candidate.telemetry == {
        "candidate_request_count": 1,
        "blank_completion_count": 1,
        "completed_turn_count": 0,
        "candidate_request_failure_count": 1,
    }


def test_successful_candidate_requests_match_recorded_turns():
    client = _ScriptedClient(
        [_response("MOVE ONE", "resp-1"), _response("MOVE TWO", "resp-2")]
    )
    candidate = GatewayCandidate(
        "http://gateway/v1", "policy", client=client, sampling_params={}
    )
    candidate.act("obs 1", "proposal")
    candidate.act("obs 2", "response")
    candidate.assert_trace_safe()
    assert candidate.candidate_request_count == len(candidate.turns) == 2
    assert [turn["response_id"] for turn in candidate.turns] == [
        "resp-1",
        "resp-2",
    ]


def test_candidate_preserves_exact_nonblank_response_for_trace_matching():
    client = _ScriptedClient([_response("  MOVE\n")])
    candidate = GatewayCandidate(
        "http://gateway/v1", "policy", client=client, sampling_params={}
    )
    assert candidate.act("obs", "proposal") == "  MOVE\n"
    assert candidate.turns[0]["response"] == "  MOVE\n"


def test_gateway_session_sampling_is_provenance_not_request_control():
    client = _ScriptedClient([_response("MOVE")])
    candidate = GatewayCandidate(
        "http://gateway/v1",
        "policy",
        client=client,
        sampling_params={"temperature": 0.2, "max_tokens": 77},
    )
    candidate.act("obs", "proposal")
    request = client.requests[0]
    assert "temperature" not in request
    assert "max_tokens" not in request
    assert candidate.sampling_provenance == {
        "source": "rllm_gateway_session",
        "params": {"temperature": 0.2, "max_tokens": 77},
    }


def test_standalone_sampling_remains_explicit():
    client = _ScriptedClient([_response("MOVE")])
    candidate = GatewayCandidate(
        "http://provider/v1",
        "policy",
        client=client,
        temperature=0.6,
        max_tokens=91,
    )
    candidate.act("obs", "proposal")
    assert client.requests[0]["temperature"] == 0.6
    assert client.requests[0]["max_tokens"] == 91
    assert candidate.sampling_provenance["source"] == "standalone_client"


def test_candidate_close_is_idempotent():
    client = _ScriptedClient([_response("MOVE")])
    candidate = GatewayCandidate("http://x/v1", "policy", client=client)
    candidate.close()
    candidate.close()
    assert client.close_count == 1


# ---------------------------------------------------------------------------
# Framework-neutral core: injection, separate budgets, cleanup, user caches.
# ---------------------------------------------------------------------------


def test_episode_core_closes_factory_candidate_and_separates_scoring_budget(
    tmp_path, monkeypatch
):
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_submit as submit

    captured: dict = {}

    class Candidate:
        turns = [{"observation": "obs", "response": "MOVE"}]
        candidate_request_count = 1
        blank_completion_count = 0
        sampling_provenance = {
            "source": "rllm_gateway_session",
            "params": {"temperature": 0.3, "max_tokens": 88},
        }

        def __init__(self):
            self.close_count = 0

        def assert_trace_safe(self):
            return None

        def raise_if_failed(self):
            return None

        def close(self):
            self.close_count += 1

    candidate = Candidate()

    def fake_seeded_case(case_path, seed, out, label):
        prepared = out / "prepared.json"
        prepared.write_text("{}")
        return prepared

    def fake_submission(case_paths, agent, *, out_root, options, **kwargs):
        captured["temp_root"] = Path(out_root).parent
        captured["options"] = options
        submission = Path(out_root) / "fake"
        submission.mkdir(parents=True)
        (submission / "submission_report.json").write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "status": "ok",
                            "score": {"w_real": 1.0, "denominator": 4.0},
                        }
                    ]
                }
            )
        )
        return submission

    monkeypatch.setattr(pilot, "seeded_case", fake_seeded_case)
    monkeypatch.setattr(submit, "run_submission", fake_submission)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", ResourceWarning)
        result = run_episode(
            tmp_path / "case.json",
            7,
            candidate_factory=lambda: candidate,
            temperature=0.9,
            max_tokens=999,
            external_scoring_temperature=0.0,
            external_scoring_max_tokens=333,
        )

    assert result["candidate_sampling"]["params"]["max_tokens"] == 88
    assert result["external_scoring"] == {
        "temperature": 0.0,
        "max_tokens": 333,
    }
    assert captured["options"].temperature == 0.0
    assert captured["options"].max_tokens == 333
    assert candidate.close_count == 1
    assert not captured["temp_root"].exists()
    assert not [item for item in seen if issubclass(item.category, ResourceWarning)]


@pytest.mark.parametrize(
    ("score", "expected_tier"),
    [
        ({"w_real": 1.0, "denominator": 4.0, "denominator_tier": "wstar_fallback"}, "wstar_fallback"),
        ({"w_real": 1.0, "denominator": 4.0}, None),
    ],
    ids=["d15-tier-present", "provisional-tier-absent"],
)
def test_episode_core_extracts_denominator_tier_when_the_scorer_reports_one(
    tmp_path, monkeypatch, score, expected_tier
):
    """WS5: ``denominator_tier`` is read from the scorer's own result and
    never fabricated when the provisional welfare-ratio tier omits it."""
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_submit as submit

    class Candidate:
        turns = [{"observation": "obs", "response": "MOVE"}]
        candidate_request_count = 1
        blank_completion_count = 0

        def assert_trace_safe(self):
            return None

        def raise_if_failed(self):
            return None

        def close(self):
            return None

    def fake_seeded_case(case_path, seed, out, label):
        prepared = out / "prepared.json"
        prepared.write_text("{}")
        return prepared

    def fake_submission(case_paths, agent, *, out_root, **kwargs):
        submission = Path(out_root) / "fake"
        submission.mkdir(parents=True)
        (submission / "submission_report.json").write_text(
            json.dumps({"cases": [{"status": "ok", "score": score}]})
        )
        return submission

    monkeypatch.setattr(pilot, "seeded_case", fake_seeded_case)
    monkeypatch.setattr(submit, "run_submission", fake_submission)
    result = run_episode(
        tmp_path / "case.json", 7, candidate_factory=Candidate
    )
    assert result["denominator_tier"] == expected_tier


def test_episode_core_re_raises_candidate_failure_swallowed_by_submission(
    tmp_path, monkeypatch
):
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_submit as submit

    error = EmptyModelResponse(
        request_count=1, blank_completion_count=1, completed_turn_count=0
    )

    class Candidate:
        turns = []
        candidate_request_count = 1
        blank_completion_count = 1

        def raise_if_failed(self):
            raise error

        def close(self):
            return None

    def fake_seeded_case(case_path, seed, out, label):
        prepared = out / "prepared.json"
        prepared.write_text("{}")
        return prepared

    def fake_submission(case_paths, agent, *, out_root, **kwargs):
        submission = Path(out_root) / "fake"
        submission.mkdir(parents=True)
        (submission / "submission_report.json").write_text(
            json.dumps({"cases": [{"status": "harness_error"}]})
        )
        return submission

    monkeypatch.setattr(pilot, "seeded_case", fake_seeded_case)
    monkeypatch.setattr(submit, "run_submission", fake_submission)
    with pytest.raises(EmptyModelResponse) as caught:
        run_episode(
            tmp_path / "case.json",
            7,
            candidate_factory=Candidate,
        )
    assert caught.value is error


def test_episode_core_preserves_structured_submission_failure(tmp_path, monkeypatch):
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_submit as submit

    class Candidate:
        turns = [{"observation": "obs", "response": "PARTIAL"}]
        candidate_request_count = 1
        blank_completion_count = 0

        def raise_if_failed(self):
            return None

        def close(self):
            return None

    def fake_seeded_case(case_path, seed, out, label):
        prepared = out / "prepared.json"
        prepared.write_text("{}")
        return prepared

    def fake_submission(case_paths, agent, *, out_root, **kwargs):
        submission = Path(out_root) / "fake"
        submission.mkdir(parents=True)
        (submission / "submission_report.json").write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "status": "harness_error",
                            "error": "RateLimitError: provider returned 429",
                            "failure_class": "retryable_infrastructure",
                            "retryable": True,
                            "failure": {
                                "class": "retryable_infrastructure",
                                "retryable": True,
                            },
                        }
                    ]
                }
            )
        )
        return submission

    monkeypatch.setattr(pilot, "seeded_case", fake_seeded_case)
    monkeypatch.setattr(submit, "run_submission", fake_submission)
    result = run_episode(
        tmp_path / "case.json", 7, candidate_factory=Candidate
    )
    assert result["status"] == "harness_error"
    assert result["failure_class"] == "retryable_infrastructure"
    assert result["retryable"] is True
    assert result["failure"]["class"] == "retryable_infrastructure"


def test_cache_defaults_are_user_scoped_and_environment_configurable(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("AEREAD_CACHE_DIR", raising=False)
    monkeypatch.delenv("AEREAD_GEMINI_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache-home"))
    configured = _configure_cache_environment()
    assert configured["AEREAD_CACHE_DIR"].startswith(str(tmp_path))
    assert configured["AEREAD_GEMINI_CACHE_DIR"].startswith(str(tmp_path))
    monkeypatch.setenv("AEREAD_CACHE_DIR", str(tmp_path / "explicit"))
    assert _configure_cache_environment()["AEREAD_CACHE_DIR"].endswith(
        "explicit"
    )


# ---------------------------------------------------------------------------
# Shipped execution and compatibility configuration.
# ---------------------------------------------------------------------------


def test_prototype_training_config_bounds_task_concurrency():
    config = json.loads(
        (REPO_ROOT / "integrations/rllm/prototype_train.yaml").read_text()
    )
    assert config["rllm"]["workflow"]["n_parallel_tasks"] == 2
    assert config["rllm"]["workflow"]["raise_on_error"] is False
    assert config["rllm"]["rollout"]["n"] == 2
    assert config["rllm"]["compact_filtering"] == {
        "enable": True,
        "mask_error": True,
    }
    assert (
        config["rllm"]["rejection_sample"]["min_trajs_per_group"]
        == config["rllm"]["rollout"]["n"]
    )


def test_rllm_constraints_pin_core_and_gateway_to_verified_revision():
    lines = (
        REPO_ROOT / "integrations/rllm/constraints.txt"
    ).read_text().splitlines()
    assert len(lines) == 2
    assert all(PINNED_REVISION in line for line in lines)
    assert lines[0].startswith("rllm @ ")
    assert lines[1].startswith("rllm-model-gateway @ ")


def _load_compat_record() -> dict:
    return json.loads(
        (REPO_ROOT / "integrations/rllm/compat.json").read_text()
    )


def test_compat_record_matches_the_pinned_revision_and_manifest():
    """WS7: the checked-in compatibility record must not silently drift from
    the revision the adapter actually pins or the manifest it actually
    ships."""
    from aeread.integrations.rllm_flow import RLLM_PINNED_REVISION

    compat = _load_compat_record()
    manifest = rllm_dataset.load_manifest()

    assert compat["rllm_revision"] == RLLM_PINNED_REVISION == PINNED_REVISION
    assert compat["model_gateway"]["revision"] == RLLM_PINNED_REVISION
    assert compat["model_gateway"]["package"] == "rllm-model-gateway"
    assert PINNED_REVISION in compat["model_gateway"]["source"]
    assert compat["caseset_version"] == manifest["caseset_version"]
    assert compat["caseset_sha256"] == manifest["caseset_sha256"]
    assert compat["protocol_version"] == manifest["protocol_version"]
    assert compat["scorer_version"] == manifest["scorer_version"]
    assert compat["prompt_spec_sha256"] == manifest["prompt_spec"]["sha256"]
    assert compat["panel_spec_sha256"] == manifest["panel_spec"]["sha256"]
    assert (
        compat["integration_tested_python_version"]
        in compat["python_versions"]
    )


def _load_check_compat_module():
    """Load the standalone CI script as a module (it ships outside the
    ``aeread`` package, alongside the compatibility record it checks)."""
    spec = importlib.util.spec_from_file_location(
        "check_compat", REPO_ROOT / "integrations/rllm/check_compat.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_compat_script_passes_for_the_recorded_revisions(
    monkeypatch, capsys
):
    check_compat = _load_check_compat_module()
    monkeypatch.setattr(
        check_compat.sys,
        "version_info",
        SimpleNamespace(major=3, minor=12, micro=0),
    )
    exit_code = check_compat.main(
        ["--python-version", "3.12", "--rllm-revision", PINNED_REVISION]
    )
    assert exit_code == 0
    assert "matches the tested revisions" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("python_version", "rllm_revision"),
    [("3.11", PINNED_REVISION), ("3.12", "0" * 40)],
    ids=["python-drift", "revision-drift"],
)
def test_check_compat_script_fails_closed_on_drift(
    monkeypatch, capsys, python_version, rllm_revision
):
    check_compat = _load_check_compat_module()
    monkeypatch.setattr(
        check_compat.sys,
        "version_info",
        SimpleNamespace(major=3, minor=12, micro=0),
    )
    exit_code = check_compat.main(
        ["--python-version", python_version, "--rllm-revision", rllm_revision]
    )
    assert exit_code == 1
    assert "mismatch" in capsys.readouterr().err


def test_entry_point_targets_the_single_decorated_rollout_shape():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    entry = project["project"]["entry-points"]["rllm.agents"]["aeread"]
    assert entry == "aeread.integrations.rllm_flow:aeread_flow"
    assert "AereadFlow" not in entry


def test_framework_neutral_core_keeps_its_compatibility_import_path():
    from aeread.integrations.episode_core import run_episode as core_run_episode
    from aeread.integrations.rllm_flow import run_episode as compatibility_export

    assert compatibility_export is core_run_episode


# ---------------------------------------------------------------------------
# Tests below use the real pinned rLLM types and dispatch when available.
# ---------------------------------------------------------------------------


def test_pinned_grouping_uses_the_stable_row_id():
    pytest.importorskip("rllm")
    from rllm.data.utils import interleave_tasks

    row = rllm_dataset.build_rows("train")[0]
    tasks, task_ids = interleave_tasks([row], group_size=2)
    assert tasks == [row, row]
    assert task_ids == [row["id"], row["id"]]


def test_pinned_train_loader_resolves_nonempty_registered_train(
    monkeypatch,
):
    pytest.importorskip("rllm")
    ui_module = types.ModuleType("rllm.cli._ui")
    ui_module.console = SimpleNamespace(print=lambda *args, **kwargs: None)
    ui_module.fail = lambda message: (_ for _ in ()).throw(RuntimeError(message))
    ui_module.info_panel = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "rllm.cli._ui", ui_module)
    rich_module = types.ModuleType("rich")
    rich_module.__path__ = []
    rich_status = types.ModuleType("rich.status")

    class Status:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    rich_status.Status = Status
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich.status", rich_status)
    train_cli = importlib.import_module("rllm.cli.train")
    train_source = Path(train_cli.__file__).read_text()
    assert re.search(r'else:\n\s+train_split = "train"', train_source)
    from rllm.data import Dataset, DatasetRegistry

    registered = Dataset(
        data=rllm_dataset.build_rows("train"),
        name="aeread",
        split="train",
    )
    calls: list[tuple[str, str]] = []

    def fake_load(cls, name, split):
        calls.append((name, split))
        return registered if (name, split) == ("aeread", "train") else None

    monkeypatch.setattr(
        DatasetRegistry, "load_dataset", classmethod(fake_load)
    )
    loaded = train_cli._load_or_pull_dataset(
        "aeread", "train", {"datasets": {}}
    )
    assert calls == [("aeread", "train")]
    assert loaded is registered
    assert len(loaded) == 16


def _flow_with_result(monkeypatch, result, *, config=None):
    pytest.importorskip("rllm")
    from rllm.types import AgentConfig

    from aeread.integrations import rllm_flow

    monkeypatch.setattr(rllm_flow, "run_episode", lambda *args, **kwargs: result)
    task = rllm_dataset.build_rows("train")[0]
    config = config or AgentConfig(
        base_url="http://x/v1", model="m", session_uid="test:0"
    )
    return rllm_flow.aeread_flow(task, config)


def test_provider_failure_raises_to_trigger_whole_rollout_retry(monkeypatch):
    pytest.importorskip("rllm")
    result = _successful_result(
        status="harness_error",
        aer=None,
        w_real=None,
        denominator=None,
        error="RateLimitError: provider returned 429",
    )
    with pytest.raises(RetryableInfrastructureError) as caught:
        _flow_with_result(monkeypatch, result)
    assert caught.value.telemetry["attempt"]["failed_by_class"] == {
        "retryable_infrastructure": 1
    }


@pytest.mark.parametrize(
    ("aer", "w_real"),
    [(0.25, 2.5), (0.0, 0.0), (-0.25, -2.5)],
    ids=["positive", "real-zero", "negative"],
)
def test_adapter_scores_every_finite_measurement_unchanged(
    monkeypatch, aer, w_real
):
    pytest.importorskip("rllm")
    episode = _flow_with_result(
        monkeypatch,
        _successful_result(aer=aer, w_real=w_real, denominator=10.0),
    )
    assert episode.trajectories[0].reward == aer
    assert episode.artifacts["aer"] == aer
    assert episode.is_correct is (aer > 0.0)
    assert episode.artifacts["measurement_counters"] == {
        "attempted": 1,
        "measured": 1,
        "failed": 0,
        "failed_by_class": {},
    }


def test_blank_result_raises_before_partial_steps_become_an_episode(monkeypatch):
    pytest.importorskip("rllm")
    result = _successful_result(
        status="harness_error",
        aer=None,
        w_real=None,
        denominator=None,
        candidate_request_count=1,
        blank_completion_count=1,
        completed_turn_count=0,
    )
    with pytest.raises(EmptyModelResponse):
        _flow_with_result(monkeypatch, result)


def test_degenerate_denominator_raises_instead_of_scoring_zero(monkeypatch):
    pytest.importorskip("rllm")
    with pytest.raises(InvalidMeasurementError):
        _flow_with_result(
            monkeypatch,
            _successful_result(aer=None, w_real=1.0, denominator=0.0),
        )


def test_unrecognized_adapter_status_raises_and_never_scores(monkeypatch):
    pytest.importorskip("rllm")
    with pytest.raises(IntegrationConfigurationError):
        _flow_with_result(
            monkeypatch,
            _successful_result(
                status="mystery_failure",
                aer=None,
                w_real=None,
                denominator=None,
            ),
        )


def test_flow_telemetry_counts_attempted_measured_and_failures(monkeypatch):
    pytest.importorskip("rllm")
    from aeread.integrations import rllm_flow

    rllm_flow.reset_flow_telemetry()
    try:
        episode = _flow_with_result(monkeypatch, _successful_result())
        with pytest.raises(InvalidMeasurementError) as caught:
            _flow_with_result(
                monkeypatch,
                _successful_result(aer=None, denominator=0.0),
            )

        expected = {
            "attempted": 2,
            "measured": 1,
            "failed": 1,
            "failed_by_class": {"invalid_measurement": 1},
        }
        assert rllm_flow.get_flow_telemetry() == expected
        assert caught.value.telemetry["flow"] == expected
        assert episode.artifacts["flow_counters"] == {
            "attempted": 1,
            "measured": 1,
            "failed": 0,
            "failed_by_class": {},
        }
    finally:
        rllm_flow.reset_flow_telemetry()


def test_evaluator_fails_closed_on_a_nonmeasurement_episode():
    pytest.importorskip("rllm")
    from aeread.integrations.rllm_eval import aeread_evaluator

    broken = SimpleNamespace(
        artifacts={
            "status": "harness_error",
            "aer": None,
            "w_real": None,
            "denominator": None,
        },
        trajectories=[],
    )
    with pytest.raises(RetryableInfrastructureError):
        aeread_evaluator(None, broken)


def test_evaluator_returns_native_eval_output_with_named_signals():
    """WS5: the evaluator returns rLLM's native type with exactly the named
    signals the readiness proposal's evaluator-output block specifies."""
    pytest.importorskip("rllm")
    from rllm.eval.types import EvalOutput, Signal

    from aeread.integrations.rllm_eval import aeread_evaluator

    manifest = rllm_dataset.load_manifest()
    dataset = rllm_dataset.build_rows("dev")[0]
    measured = SimpleNamespace(
        artifacts={
            "status": "ok",
            "aer": 0.031,
            "w_real": 3.1,
            "denominator": 100.0,
            "blank_completion_count": 0,
            "dataset": dataset,
            "caseset_sha256": manifest["caseset_sha256"],
            "model": "policy-a",
            "candidate_sampling": {
                "source": "rllm_gateway_session",
                "params": {"temperature": 0.2, "max_tokens": 77},
            },
            "prompt_spec": manifest["prompt_spec"],
            "panel_spec": manifest["panel_spec"],
            "scorer_version": manifest["scorer_version"],
            "scorer": {
                "version": manifest["scorer_version"],
                "tier": "d15",
            },
        },
        trajectories=[],
    )
    output = aeread_evaluator(None, measured)
    assert isinstance(output, EvalOutput)
    assert output.reward == pytest.approx(0.031)
    # is_correct is documented as a positive-welfare-rate compatibility
    # diagnostic, never AERead's benchmark headline -- but it stays the
    # aer > 0 Boolean rLLM's Accuracy display consumes.
    assert output.is_correct is True
    assert all(isinstance(signal, Signal) for signal in output.signals)
    assert {signal.name for signal in output.signals} == {
        "episode_aer",
        "w_real",
        "denominator",
        "valid_measurement",
        "blank_completion_count",
    }
    values = {signal.name: signal.value for signal in output.signals}
    assert values["episode_aer"] == pytest.approx(0.031)
    assert values["w_real"] == pytest.approx(3.1)
    assert values["denominator"] == pytest.approx(100.0)
    assert values["valid_measurement"] == 1.0
    assert values["blank_completion_count"] == 0.0
    assert output.metadata["dataset"] == dataset
    assert output.metadata["caseset_sha256"] == manifest["caseset_sha256"]
    assert output.metadata["model"] == "policy-a"
    assert output.metadata["candidate_sampling"] == {
        "source": "rllm_gateway_session",
        "params": {"temperature": 0.2, "max_tokens": 77},
    }
    assert output.metadata["prompt_spec"] == manifest["prompt_spec"]
    assert output.metadata["panel_spec"] == manifest["panel_spec"]
    assert output.metadata["scorer_version"] == manifest["scorer_version"]
    assert output.metadata["scorer"] == {
        "version": manifest["scorer_version"],
        "tier": "d15",
    }


def test_evaluator_attaches_tier_metadata_when_available():
    pytest.importorskip("rllm")
    from aeread.integrations.rllm_eval import aeread_evaluator

    measured = SimpleNamespace(
        artifacts={
            "status": "ok",
            "aer": 0.031,
            "w_real": 3.1,
            "denominator": 100.0,
            "denominator_tier": "wstar_fallback",
            "blank_completion_count": 0,
        },
        trajectories=[],
    )
    output = aeread_evaluator(None, measured)
    signals = {signal.name: signal for signal in output.signals}
    assert signals["episode_aer"].metadata == {"tier": "wstar_fallback"}
    assert signals["w_real"].metadata == {"tier": "wstar_fallback"}
    assert signals["denominator"].metadata == {"tier": "wstar_fallback"}
    # valid_measurement and blank_completion_count are not tier-scoped.
    assert signals["valid_measurement"].metadata == {}
    assert signals["blank_completion_count"].metadata == {}
    assert output.metadata["denominator_tier"] == "wstar_fallback"


def test_evaluator_omits_tier_metadata_when_unavailable():
    pytest.importorskip("rllm")
    from aeread.integrations.rllm_eval import aeread_evaluator

    measured = SimpleNamespace(
        artifacts={
            "status": "ok",
            "aer": 0.031,
            "w_real": 3.1,
            "denominator": 100.0,
            "blank_completion_count": 0,
        },
        trajectories=[],
    )
    output = aeread_evaluator(None, measured)
    signals = {signal.name: signal for signal in output.signals}
    assert signals["episode_aer"].metadata == {}
    assert output.metadata["denominator_tier"] is None


def test_flow_propagates_denominator_tier_from_result_into_artifacts(monkeypatch):
    """WS5: ``run_episode``'s ``denominator_tier`` (present only for the D15
    tier, absent for the provisional welfare-ratio tier) reaches
    ``episode.artifacts`` unchanged -- it is fabricated for neither tier.
    The evaluator's own tier-metadata behavior is covered directly by
    ``test_evaluator_attaches_tier_metadata_when_available`` and
    ``test_evaluator_omits_tier_metadata_when_unavailable``."""
    pytest.importorskip("rllm")

    episode = _flow_with_result(
        monkeypatch,
        _successful_result(denominator_tier="wstar_fallback"),
    )
    assert episode.artifacts["denominator_tier"] == "wstar_fallback"

    provisional_episode = _flow_with_result(monkeypatch, _successful_result())
    assert provisional_episode.artifacts["denominator_tier"] is None


def _load_pinned_trainer_module(monkeypatch, module_name):
    """Load a trainer leaf without installing backend-only dependencies."""
    rllm = pytest.importorskip("rllm")
    rllm_root = Path(rllm.__file__).resolve().parent
    for package_name, relative_path in (
        ("rllm.trainer", "trainer"),
        ("rllm.trainer.algorithms", "trainer/algorithms"),
    ):
        package = types.ModuleType(package_name)
        package.__path__ = [str(rllm_root / relative_path)]
        monkeypatch.setitem(sys.modules, package_name, package)
    return importlib.import_module(module_name)


def test_finite_rewards_reach_grpo_advantage_input_unchanged(monkeypatch):
    import numpy as np

    rl_algo = _load_pinned_trainer_module(
        monkeypatch, "rllm.trainer.algorithms.rl_algo"
    )

    rewards = np.array([0.25, 0.0, -0.25])
    before = rewards.copy()
    advantages, _ = rl_algo.calculate_grpo_advantages_per_group(
        rewards, norm_adv_by_std_in_grpo=False
    )
    assert rewards.tolist() == before.tolist()
    assert advantages.tolist() == pytest.approx([0.25, 0.0, -0.25])


def test_compact_filtering_drops_an_incomplete_prompt_group(monkeypatch):
    omega = types.ModuleType("omegaconf")
    omega.DictConfig = dict
    omega.OmegaConf = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "omegaconf", omega)
    config_module = _load_pinned_trainer_module(
        monkeypatch, "rllm.trainer.algorithms.config"
    )
    transform_module = importlib.import_module(
        "rllm.trainer.algorithms.transform"
    )
    from rllm.types import Episode, Step, Trajectory
    from rllm.workflows.workflow import TerminationReason

    measured = Episode(
        id="case:0",
        trajectories=[
            Trajectory(
                name="under_test",
                steps=[Step(model_response="MOVE", action="MOVE")],
                reward=0.25,
            )
        ],
    )
    failed = Episode(
        id="case:1",
        termination_reason=TerminationReason.ERROR,
        trajectories=[
            Trajectory(
                name="under_test",
                steps=[Step(model_response="PARTIAL", action="PARTIAL")],
                reward=0.0,
            )
        ],
    )
    groups, metrics = transform_module.transform_episodes_to_trajectory_groups(
        [measured, failed],
        config_module.TransformConfig(),
        config_module.CompactFilteringConfig(enable=True, mask_error=True),
    )
    assert metrics["groups/num_trajs_before_filter"] == 2
    assert metrics["groups/num_trajs_after_filter"] == 1
    assert len(groups) == 1
    assert len(groups[0].trajectories) == 1

    config = json.loads(
        (REPO_ROOT / "integrations/rllm/prototype_train.yaml").read_text()
    )["rllm"]
    minimum = config["rejection_sample"]["min_trajs_per_group"]
    optimizer_groups = [
        group for group in groups if len(group.trajectories) >= minimum
    ]
    assert optimizer_groups == []


def test_decorated_sync_rollouts_are_concurrent_through_run_agent_flow(
    monkeypatch,
):
    pytest.importorskip("rllm")
    from rllm.types import AgentConfig, run_agent_flow

    from aeread.integrations import rllm_flow

    def slow_episode(*args, **kwargs):
        time.sleep(0.25)
        return _successful_result()

    monkeypatch.setattr(rllm_flow, "run_episode", slow_episode)
    task = rllm_dataset.build_rows("train")[0]
    configs = [
        AgentConfig(
            base_url="http://x/v1", model="m", session_uid=f"task:{index}"
        )
        for index in range(2)
    ]

    async def run_both():
        return await asyncio.gather(
            *(
                run_agent_flow(rllm_flow.aeread_flow, task, config)
                for config in configs
            )
        )

    started = time.perf_counter()
    episodes = asyncio.run(run_both())
    elapsed = time.perf_counter() - started
    assert len(episodes) == 2
    assert elapsed < 0.45, f"two 250ms rollouts serialized in {elapsed:.3f}s"


def test_flow_records_gateway_sampling_and_ignores_candidate_metadata(
    monkeypatch,
):
    pytest.importorskip("rllm")
    from rllm.types import AgentConfig

    from aeread.integrations import rllm_flow

    observed: dict = {}

    def fake_episode(*args, **kwargs):
        candidate = kwargs["candidate_factory"]()
        observed["candidate"] = candidate
        observed["external_temperature"] = kwargs[
            "external_scoring_temperature"
        ]
        observed["external_max_tokens"] = kwargs[
            "external_scoring_max_tokens"
        ]
        try:
            return _successful_result(
                candidate_sampling=candidate.sampling_provenance,
                score={"tier": "d15"},
                external_scoring={
                    "temperature": kwargs["external_scoring_temperature"],
                    "max_tokens": kwargs["external_scoring_max_tokens"],
                },
            )
        finally:
            candidate.close()

    monkeypatch.setattr(rllm_flow, "run_episode", fake_episode)
    config = AgentConfig(
        base_url="http://gateway/v1",
        model="policy",
        session_uid="task:0",
        sampling_params={"temperature": 0.2, "max_tokens": 77},
        metadata={
            "temperature": 0.95,
            "max_tokens": 9999,
            "external_scoring_temperature": 0.0,
            "external_scoring_max_tokens": 333,
        },
    )
    episode = rllm_flow.aeread_flow(
        rllm_dataset.build_rows("train")[0], config
    )

    candidate = observed["candidate"]
    assert candidate.temperature is None
    assert candidate.max_tokens is None
    assert observed["external_temperature"] == 0.0
    assert observed["external_max_tokens"] == 333
    assert episode.artifacts["candidate_sampling"] == {
        "source": "rllm_gateway_session",
        "params": {"temperature": 0.2, "max_tokens": 77},
    }
    manifest = rllm_dataset.load_manifest()
    assert episode.artifacts["model"] == "policy"
    assert episode.artifacts["caseset_sha256"] == manifest["caseset_sha256"]
    assert episode.artifacts["prompt_spec"] == manifest["prompt_spec"]
    assert episode.artifacts["panel_spec"] == manifest["panel_spec"]
    assert episode.artifacts["scorer_version"] == manifest["scorer_version"]
    assert episode.artifacts["scorer"] == {
        "version": manifest["scorer_version"],
        "tier": "d15",
    }
    assert episode.artifacts["dataset"] == {
        name: rllm_dataset.build_rows("train")[0][name]
        for name in (
            "id",
            "case_id",
            "case_resource",
            "case_sha256",
            "seed",
            "split",
            "caseset_version",
            "caseset_sha256",
            "protocol_version",
            "prompt_spec",
            "panel_spec",
            "scorer_version",
        )
    }
    assert episode.artifacts["external_scoring"]["max_tokens"] == 333


def test_simulated_episode_constructor_change_fails_with_targeted_pin():
    pytest.importorskip("rllm")
    from aeread.integrations.rllm_flow import (
        RllmCompatibilityError,
        _require_rllm_compatibility,
    )

    class ChangedEpisode:
        model_fields = {"trajectories": object()}

    with pytest.raises(RllmCompatibilityError) as caught:
        _require_rllm_compatibility(episode_type=ChangedEpisode)
    assert PINNED_REVISION in str(caught.value)
    assert "artifacts" in str(caught.value)


def test_flow_uses_direct_pinned_types_and_decorator():
    pytest.importorskip("rllm")
    from rllm.eval.agent_loader import _validate_agent
    from rllm.eval.rollout_decorator import AgentFlowFn
    from rllm.types import Episode, Step, Trajectory

    from aeread.integrations import rllm_flow

    assert isinstance(rllm_flow.aeread_flow, AgentFlowFn)
    assert rllm_flow.Episode is Episode
    assert rllm_flow.Trajectory is Trajectory
    assert rllm_flow.Step is Step
    assert not hasattr(rllm_flow, "AereadFlow")
    _validate_agent(rllm_flow.aeread_flow, "aeread")


def _load_pinned_engine(monkeypatch):
    """Load pinned engine code without installing its server-only extras."""
    rllm = pytest.importorskip("rllm")
    if "rllm.engine.agentflow_engine" in sys.modules:
        return sys.modules["rllm.engine.agentflow_engine"]

    rllm_root = Path(rllm.__file__).resolve().parents[1]
    gateway_package = types.ModuleType("rllm_model_gateway")
    gateway_package.__path__ = [
        str(rllm_root / "rllm-model-gateway/src/rllm_model_gateway")
    ]
    monkeypatch.setitem(sys.modules, "rllm_model_gateway", gateway_package)

    from rllm.types import Task

    data_package = types.ModuleType("rllm.data")
    data_package.__path__ = []
    data_utils = types.ModuleType("rllm.data.utils")

    def task_from_row(row, task_id):
        return Task(id=str(task_id), instruction="", metadata=row)

    data_utils.task_from_row = task_from_row
    data_package.utils = data_utils
    monkeypatch.setitem(sys.modules, "rllm.data", data_package)
    monkeypatch.setitem(sys.modules, "rllm.data.utils", data_utils)
    return importlib.import_module("rllm.engine.agentflow_engine")


def test_scripted_rollout_group_reaches_expected_grpo_rewards_and_advantages(
    monkeypatch,
):
    pytest.importorskip("rllm")
    import numpy as np
    from rllm.types import AgentConfig, run_agent_flow

    from aeread.integrations import rllm_flow
    from aeread.integrations.rllm_eval import aeread_evaluator

    engine_module = _load_pinned_engine(monkeypatch)
    from rllm_model_gateway.models import TraceRecord

    omega = types.ModuleType("omegaconf")
    omega.DictConfig = dict
    omega.OmegaConf = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "omegaconf", omega)
    config_module = _load_pinned_trainer_module(
        monkeypatch, "rllm.trainer.algorithms.config"
    )
    transform_module = importlib.import_module(
        "rllm.trainer.algorithms.transform"
    )
    advantage_module = importlib.import_module(
        "rllm.trainer.algorithms.advantage"
    )

    responses = [
        "PUBLIC ACTION\nNO_ACTION",
        "PUBLIC ACTION\nPROPOSE 1 X",
    ]
    expected_rewards = [-0.25, 0.25]
    scripted_results = iter(
        [
            _successful_result(
                aer=reward,
                w_real=reward * 10.0,
                denominator=10.0,
                turns=[
                    {
                        "phase": "proposal",
                        "observation": "you are agent a1",
                        "response": response,
                        "response_id": f"chatcmpl-scripted-{index}",
                    }
                ],
            )
            for index, (response, reward) in enumerate(
                zip(responses, expected_rewards, strict=True)
            )
        ]
    )
    monkeypatch.setattr(
        rllm_flow,
        "run_episode",
        lambda *args, **kwargs: next(scripted_results),
    )
    task = rllm_dataset.build_rows("train")[0]

    async def run_scripted_rollouts():
        episodes = []
        for index in range(2):
            config = AgentConfig(
                base_url="http://scripted.invalid/v1",
                model="scripted-policy",
                session_uid=f"shared-task:{index}",
            )
            episodes.append(
                await run_agent_flow(rllm_flow.aeread_flow, task, config)
            )
        return episodes

    raw_episodes = asyncio.run(run_scripted_rollouts())
    enriched_episodes = []
    evaluator_rewards = []
    for index, (raw, response) in enumerate(
        zip(raw_episodes, responses, strict=True)
    ):
        uid = f"shared-task:{index}"
        trace = TraceRecord(
            trace_id=f"trace-scripted-{index}",
            session_id=uid,
            messages=[{"role": "user", "content": "you are agent a1"}],
            prompt_token_ids=[10, 11],
            response_message={"role": "assistant", "content": response},
            completion_token_ids=[20 + index, 30 + index],
            logprobs=[-0.1, -0.2],
        )
        enriched = engine_module.enrich_episode_with_traces(
            raw, [trace], uid, task, strict=True
        )
        enriched_episodes.append(enriched)
        evaluator_rewards.append(aeread_evaluator(task, enriched).reward)

    groups, metrics = transform_module.transform_episodes_to_trajectory_groups(
        enriched_episodes,
        config_module.TransformConfig(),
        config_module.CompactFilteringConfig(enable=True, mask_error=True),
    )
    assert metrics["groups/num_groups"] == 1
    assert metrics["groups/num_trajs_after_filter"] == 2
    assert len(groups) == 1
    group_rewards = [
        trajectory.reward for trajectory in groups[0].trajectories
    ]
    assert evaluator_rewards == pytest.approx(expected_rewards)
    assert group_rewards == pytest.approx(expected_rewards)

    advantage_module.collect_reward_and_advantage_from_trajectory_groups(
        groups,
        config_module.AlgorithmConfig(norm_adv_by_std_in_grpo=True),
    )
    actual_advantages = [
        trajectory.steps[0].advantage
        for trajectory in groups[0].trajectories
    ]
    expected_scale = 0.25 / (0.25 + 1e-6)
    expected_advantages = [-expected_scale, expected_scale]
    assert np.isfinite(actual_advantages).all()
    assert actual_advantages == pytest.approx(expected_advantages)


def test_enriched_step_matches_response_tokens_and_trace_identity(monkeypatch):
    engine_module = _load_pinned_engine(monkeypatch)
    from rllm.types import Episode, Step, Trajectory
    from rllm_model_gateway.models import TraceRecord

    from aeread.integrations.rllm_eval import aeread_evaluator

    raw = Episode(
        trajectories=[
            Trajectory(
                name="under_test",
                steps=[Step(model_response="MOVE", action="MOVE", done=True)],
            )
        ],
        artifacts={
            "status": "ok",
            "aer": 0.1,
            "w_real": 1.0,
            "denominator": 10.0,
            "candidate_request_count": 1,
            "completed_turn_count": 1,
            "blank_completion_count": 0,
            "is_validation": False,
        },
    )
    trace = TraceRecord(
        trace_id="trace-one",
        session_id="task:0",
        messages=[{"role": "user", "content": "obs"}],
        prompt_token_ids=[10, 11],
        response_message={"role": "assistant", "content": "MOVE"},
        completion_token_ids=[20, 21],
        logprobs=[-0.1, -0.2],
    )
    enriched = engine_module.enrich_episode_with_traces(
        raw, [trace], "task:0", {"case_path": "case.json"}, strict=True
    )
    step = enriched.trajectories[0].steps[0]
    assert step.model_response == step.action == "MOVE"
    assert step.response_ids == [20, 21]
    assert step.id == "trace-one"
    output = aeread_evaluator(None, enriched)
    assert output.reward == pytest.approx(0.1)
    signals = {signal.name: signal.value for signal in output.signals}
    assert signals["episode_aer"] == pytest.approx(0.1)
    assert signals["w_real"] == pytest.approx(1.0)
    assert signals["denominator"] == pytest.approx(10.0)
    assert signals["valid_measurement"] == 1.0
    assert signals["blank_completion_count"] == 0.0


def test_trailing_malformed_gateway_trace_is_dropped_before_validation(monkeypatch):
    engine_module = _load_pinned_engine(monkeypatch)
    from rllm.types import Episode, Step, Trajectory
    from rllm_model_gateway.models import TraceRecord

    from aeread.integrations.rllm_eval import aeread_evaluator

    raw = Episode(
        trajectories=[
            Trajectory(
                name="under_test",
                steps=[Step(model_response="MOVE", action="MOVE", done=True)],
            )
        ],
        artifacts={
            "status": "ok",
            "aer": 0.1,
            "w_real": 1.0,
            "denominator": 10.0,
            "candidate_request_count": 1,
            "completed_turn_count": 1,
            "blank_completion_count": 0,
            "is_validation": False,
        },
    )
    traces = [
        TraceRecord(
            trace_id="trace-one",
            session_id="task:0",
            messages=[{"role": "user", "content": "obs"}],
            prompt_token_ids=[10, 11],
            response_message={"role": "assistant", "content": "MOVE"},
            completion_token_ids=[20, 21],
            logprobs=[-0.1, -0.2],
        ),
        TraceRecord(
            trace_id="trace-trailing-malformed",
            session_id="task:0",
            response_message={"role": "assistant", "content": ""},
        ),
    ]
    enriched = engine_module.enrich_episode_with_traces(
        raw, traces, "task:0", {"case_path": "case.json"}, strict=True
    )

    assert enriched.metrics["steps_collected"] == 2
    assert enriched.metrics["steps_used"] == 1
    assert len(enriched.trajectories[0].steps) == 1
    output = aeread_evaluator(None, enriched)
    assert output.reward == pytest.approx(0.1)


def test_trace_text_mismatch_fails_closed(monkeypatch):
    engine_module = _load_pinned_engine(monkeypatch)
    from rllm.types import Episode, Step, Trajectory
    from rllm_model_gateway.models import TraceRecord

    from aeread.integrations.gateway_candidate import CandidateTraceMismatch
    from aeread.integrations.rllm_eval import aeread_evaluator

    raw = Episode(
        trajectories=[
            Trajectory(steps=[Step(model_response="MOVE", action="MOVE")])
        ],
        artifacts={
            "status": "ok",
            "aer": 0.1,
            "candidate_request_count": 1,
            "completed_turn_count": 1,
            "is_validation": False,
        },
    )
    trace = TraceRecord(
        trace_id="wrong-trace",
        session_id="task:0",
        messages=[],
        prompt_token_ids=[1],
        response_message={"role": "assistant", "content": "OTHER"},
        completion_token_ids=[2],
    )
    enriched = engine_module.enrich_episode_with_traces(
        raw, [trace], "task:0", {}, strict=True
    )
    with pytest.raises(CandidateTraceMismatch):
        aeread_evaluator(None, enriched)


def test_scripted_429_retries_clean_whole_session(monkeypatch):
    engine_module = _load_pinned_engine(monkeypatch)
    import httpx
    from openai import RateLimitError
    from rllm.types import Episode, Step, Task, Trajectory

    request = httpx.Request("POST", "http://gateway/v1/chat/completions")
    response_429 = httpx.Response(429, request=request)
    rate_error = RateLimitError(
        "rate limited", response=response_429, body={"error": "rate limited"}
    )
    client = _ScriptedClient([rate_error, _response("MOVE", "success")])

    class Gateway:
        def __init__(self):
            self.traces: list[str] = []
            self.deleted: list[str] = []

        async def adelete_session(self, uid):
            self.deleted.append(uid)
            self.traces.clear()
            return 1

    gateway = Gateway()
    rollout_engine = object.__new__(engine_module.AgentFlowEngine)
    rollout_engine._semaphore = asyncio.Semaphore(1)
    rollout_engine.retry_limit = 2
    rollout_engine.raise_on_error = True
    rollout_engine.gateway = gateway

    async def fake_run_single(self, task, uid, is_validation=False):
        with GatewayCandidate(
            "http://gateway/v1",
            "policy",
            client=client,
            sampling_params={"temperature": 0.2},
        ) as candidate:
            try:
                action = candidate.act("obs", "proposal")
            except RateLimitError:
                gateway.traces.append("failed-attempt-trace")
                raise
            gateway.traces.append("successful-attempt-trace")
            return Episode(
                trajectories=[
                    Trajectory(
                        name="under_test",
                        steps=[Step(model_response=action, action=action)],
                    )
                ]
            )

    rollout_engine._run_single = types.MethodType(
        fake_run_single, rollout_engine
    )
    task = Task(id="task", instruction="", metadata={})
    result = asyncio.run(
        rollout_engine.process_task_with_retry(task, "task", 0, 0)
    )
    episode = result[3]

    assert len(client.requests) == 2
    assert client.close_count == 2
    assert gateway.deleted == ["task:0"]
    assert gateway.traces == ["successful-attempt-trace"]
    assert len(episode.trajectories[0].steps) == 1
