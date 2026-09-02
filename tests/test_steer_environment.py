"""Provider-free scheduler coverage for the ``steer`` environment plugin.

Mode A: a single agent, one phase, one logical action. These tests never
touch pandas or the bridge subprocess -- only the cached, flattened JSON at
``bridges/steer-data/<element>/cases.jsonl`` that ``cases.py`` already wrote,
read the same way the plugin reads it at runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.execution import CanonicalResponse
from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.environment import SteerPlugin, family_manifest, register_plugin


def _cache_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_STEER_DATA_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data",
    )
    root = Path(candidate)
    marker = root / "transitivity" / "cases.jsonl"
    if not marker.is_file():
        pytest.skip(
            f"flattened cache not built yet at {root}; run "
            "src/aeread_families/steer/cases.py first",
            allow_module_level=True,
        )
    return root


CACHE_ROOT = _cache_root()
CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "steer"


def _case(element: str, question_id: str) -> CaseManifest:
    branch = steer_cases.BRANCH_BY_ELEMENT[element]
    path = CASES_DIR / branch / f"steer.{element}.{question_id}.json"
    if not path.is_file():
        pytest.skip(f"case file not built yet at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_steer_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_steer_environment",
        suite_version="0.1.0",
        block_id="block_steer_environment",
        sampling_plan_id="sampling_steer_environment",
        analysis_plan_id="analysis_steer_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_steer_environment",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"agent": "scripted_agent"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _plugin() -> SteerPlugin:
    return SteerPlugin(steer_data_root=CACHE_ROOT)


def _first_admitted_question_id(element: str) -> str:
    path = CACHE_ROOT / element / "cases.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        return json.loads(handle.readline())["question_id"]


# ---------------------------------------------------------------------------
# Registration and declaration shape.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = _plugin()
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name for name in REQUIRED_FAMILY_PLUGIN_HOOKS if callable(getattr(plugin, name, None))
    }


def test_register_plugin_requires_steer_data_root_when_no_plugin_supplied() -> None:
    with pytest.raises(ValueError, match="steer_data_root is required"):
        register_plugin(PluginRegistry())


def test_family_manifest_declares_mode_a_single_phase() -> None:
    manifest = family_manifest()
    assert manifest.environment.phase_specs == ("answer_question",)
    assert manifest.environment.needs_tools is False
    assert manifest.environment.needs_sandbox is False
    assert manifest.measurement.direction == "maximize"


def test_phases_is_one_phase_one_logical_action_no_next_phase() -> None:
    case = _case("transitivity", _first_admitted_question_id("transitivity"))
    family_case = _plugin().validate_payload(case.payload)
    phases = _plugin().phases(family_case)
    assert len(phases) == 1
    phase = phases[0]
    assert phase.mode == "single"
    assert phase.max_logical_actions == 1
    assert phase.invalid_action_policy == "family_defined"
    assert phase.next_phases == ()


# ---------------------------------------------------------------------------
# validate_payload.
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_a_real_written_case() -> None:
    case = _case("transitivity", _first_admitted_question_id("transitivity"))
    family_case = _plugin().validate_payload(case.payload)
    assert family_case["element"] == "transitivity"


@pytest.mark.parametrize(
    "mutation,message",
    [
        (lambda payload: {**payload, "element": "independence"}, "not one of the declared elements"),
        (lambda payload: {**payload, "question_id": ""}, "question_id must be a non-empty string"),
        (lambda payload: {**payload, "options_count": 1}, "options_count must be an integer >= 2"),
        (lambda payload: {**payload, "source_sha256": "not-a-hash"}, "64 lowercase hexadecimal"),
        (lambda payload: {k: v for k, v in payload.items() if k != "pins"}, "must contain exactly"),
    ],
)
def test_validate_payload_rejects_malformed_shapes(mutation, message) -> None:
    case = _case("transitivity", _first_admitted_question_id("transitivity"))
    payload = json.loads(canonical_json_bytes(case.payload))
    mutated = mutation(payload)
    with pytest.raises(ValueError, match=message):
        _plugin().validate_payload(mutated)


def test_validate_payload_rejects_wrong_upstream_pin() -> None:
    case = _case("transitivity", _first_admitted_question_id("transitivity"))
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["pins"] = {**payload["pins"], "upstream_commit": "0" * 40}
    with pytest.raises(ValueError, match="wrong upstream commit"):
        _plugin().validate_payload(payload)


# ---------------------------------------------------------------------------
# initial_state / observe: reads the cached row, verifies source_sha256.
# ---------------------------------------------------------------------------


def test_initial_state_and_observe_reflect_the_cached_question_and_options() -> None:
    element = "plurality_voting"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    plugin = _plugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    observation = plugin.observe(family_case, state, "agent", plugin.phases(family_case)[0])

    assert observation["element"] == element
    assert isinstance(observation["question_text"], str) and observation["question_text"]
    assert len(observation["options"]) == family_case["options_count"]
    assert [option["option_id"] for option in observation["options"]] == list(
        range(family_case["options_count"])
    )


def test_initial_state_rejects_a_source_sha256_mismatch() -> None:
    element = "transitivity"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["source_sha256"] = "0" * 64
    plugin = _plugin()
    family_case = plugin.validate_payload(payload)
    with pytest.raises(ValueError, match="source_sha256 does not match"):
        plugin.initial_state(family_case, cell=None)


def test_initial_state_and_build_scorer_reject_a_tampered_row_whose_own_source_sha256_field_agrees(
    tmp_path: Path,
) -> None:
    """Critical review finding: the cache's own ``source_sha256`` FIELD is a
    bare stored value copied once at import time, never recomputed --
    comparing it to the payload's declared value proves nothing about the
    content sitting right next to it. ``initial_state``/``build_scorer``
    must recompute the digest from the row's own
    ``question_text``/``options``/``correct_option_id`` and compare THAT,
    so a cache row tampered (or corrupted) without also updating its own
    ``source_sha256`` field is actually caught."""
    element = "transitivity"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    plugin = _plugin()
    family_case = plugin.validate_payload(case.payload)
    original_row = plugin._load_cached_row(element, question_id)

    tampered_row = {**original_row, "question_text": "TAMPERED QUESTION TEXT"}
    # The tampering leaves the row's own stored source_sha256 untouched --
    # exactly the scenario the bare self-comparison could never catch.
    assert tampered_row["source_sha256"] == original_row["source_sha256"]

    tampered_cache_root = tmp_path / "steer-data"
    element_dir = tampered_cache_root / element
    element_dir.mkdir(parents=True)
    (element_dir / "cases.jsonl").write_text(
        json.dumps(tampered_row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tampered_plugin = SteerPlugin(steer_data_root=tampered_cache_root)

    with pytest.raises(ValueError, match="source_sha256 does not match"):
        tampered_plugin.initial_state(family_case, cell=None)
    with pytest.raises(ValueError, match="source_sha256 does not match"):
        tampered_plugin.build_scorer(family_case)


def test_observe_rejects_a_seat_not_active_in_this_family() -> None:
    case = _case("transitivity", _first_admitted_question_id("transitivity"))
    plugin = _plugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    with pytest.raises(ValueError, match="not active"):
        plugin.observe(family_case, state, "someone_else", plugin.phases(family_case)[0])


# ---------------------------------------------------------------------------
# parse_action / legal: the four non-golden shapes of spec section 4.
# ---------------------------------------------------------------------------


def _prepared(element: str = "transitivity"):
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    plugin = _plugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    phase = plugin.phases(family_case)[0]
    return plugin, family_case, state, phase


def test_parse_action_accepts_a_well_formed_option_choice() -> None:
    plugin, family_case, state, phase = _prepared()
    result = plugin.parse_action(family_case, state, "agent", phase, '{"option_id": 0}')
    assert result.ok
    assert result.action == {"option_id": 0}


def test_parse_action_accepts_a_canonical_response() -> None:
    plugin, family_case, state, phase = _prepared()
    response = CanonicalResponse(
        text='{"option_id": 1}',
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
    result = plugin.parse_action(family_case, state, "agent", phase, response)
    assert result.ok
    assert result.action == {"option_id": 1}


def test_parse_action_rejects_free_text_prose_as_malformed() -> None:
    """Golden 4 (malformed-operational): free-text prose, never coerced."""
    plugin, family_case, state, phase = _prepared()
    result = plugin.parse_action(
        family_case, state, "agent", phase, "I believe the answer is option B."
    )
    assert not result.ok
    assert result.error_code == "malformed_answer_json"


@pytest.mark.parametrize(
    "raw,error_code",
    [
        ('{"option_id": 0, "extra": 1}', "malformed_answer_shape"),
        ("[0]", "malformed_answer_shape"),
        ('{"option_id": "0"}', "malformed_option_id"),
        ('{"option_id": true}', "malformed_option_id"),
    ],
)
def test_parse_action_rejects_other_malformed_shapes(raw: str, error_code: str) -> None:
    plugin, family_case, state, phase = _prepared()
    result = plugin.parse_action(family_case, state, "agent", phase, raw)
    assert not result.ok
    assert result.error_code == error_code


def test_parse_action_rejects_noncanonical_response_types() -> None:
    plugin, family_case, state, phase = _prepared()
    result = plugin.parse_action(family_case, state, "agent", phase, 12345)
    assert not result.ok
    assert result.error_code == "noncanonical_response"


def test_legal_accepts_an_in_range_option_id() -> None:
    plugin, family_case, state, phase = _prepared()
    legality = plugin.legal(family_case, state, "agent", phase, {"option_id": 0})
    assert legality.legal


def test_legal_rejects_an_out_of_range_option_id() -> None:
    """Golden 3 (invalid-unauthorized): an option_id absent from this

    question's own option set, never coerced to option 0.
    """
    plugin, family_case, state, phase = _prepared()
    out_of_range = family_case["options_count"]
    legality = plugin.legal(family_case, state, "agent", phase, {"option_id": out_of_range})
    assert not legality.legal
    assert legality.reason == "option_id_out_of_range"


def test_legal_rejects_a_negative_option_id() -> None:
    plugin, family_case, state, phase = _prepared()
    legality = plugin.legal(family_case, state, "agent", phase, {"option_id": -1})
    assert not legality.legal
    assert legality.reason == "option_id_out_of_range"


# ---------------------------------------------------------------------------
# step / terminal / outcome.
# ---------------------------------------------------------------------------


class _Envelope:
    def __init__(self, *, valid: bool, action=None, parse=None, legality=None) -> None:
        self.valid = valid
        self.action = action
        self.parse = parse
        self.legality = legality


class _Result:
    def __init__(self, *, ok=None, error_code=None, legal=None, reason=None) -> None:
        self.ok = ok
        self.error_code = error_code
        self.legal = legal
        self.reason = reason


def test_step_records_a_valid_submission_as_answered() -> None:
    plugin, family_case, state, phase = _prepared()
    envelope = _Envelope(valid=True, action={"option_id": 0})
    transition = plugin.step(family_case, state, phase, {"agent": envelope})
    assert transition.next_phase_id is None
    assert transition.state["termination"] == "answered"
    assert transition.state["selected_option_id"] == 0
    assert transition.state["failure_code"] is None

    terminal = plugin.terminal(family_case, transition.state)
    assert terminal == {"reason": "answered", "selected_option_id": 0, "failure_code": None}
    outcome = plugin.outcome(family_case, terminal)
    assert outcome == {
        "termination_reason": "answered",
        "selected_option_id": 0,
        "failure_code": None,
    }


def test_step_records_an_illegal_submission_as_error() -> None:
    plugin, family_case, state, phase = _prepared()
    envelope = _Envelope(
        valid=False,
        action=None,
        parse=_Result(ok=True),
        legality=_Result(legal=False, reason="option_id_out_of_range"),
    )
    transition = plugin.step(family_case, state, phase, {"agent": envelope})
    assert transition.state["termination"] == "error"
    assert transition.state["selected_option_id"] is None
    assert transition.state["failure_code"] == "option_id_out_of_range"

    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "error"
    assert terminal["failure_code"] == "option_id_out_of_range"


def test_step_records_a_malformed_submission_as_error() -> None:
    plugin, family_case, state, phase = _prepared()
    envelope = _Envelope(
        valid=False,
        action=None,
        parse=_Result(ok=False, error_code="malformed_answer_json"),
        legality=None,
    )
    transition = plugin.step(family_case, state, phase, {"agent": envelope})
    assert transition.state["failure_code"] == "malformed_answer_json"
    terminal = plugin.terminal(family_case, transition.state)
    assert terminal["reason"] == "error"
    assert terminal["failure_code"] == "malformed_answer_json"


def test_terminal_is_none_before_a_submission_is_stepped() -> None:
    plugin, family_case, state, phase = _prepared()
    del phase
    assert plugin.terminal(family_case, state) is None


# ---------------------------------------------------------------------------
# build_scorer wiring (real coverage lives in tests/test_steer_measurement.py
# and tests/test_steer_goldens.py; this just pins the environment.py hook
# itself never silently regresses back to the milestone-1 placeholder).
# ---------------------------------------------------------------------------


def test_build_scorer_returns_a_scorer_for_this_cases_own_question() -> None:
    plugin, family_case, _state, _phase = _prepared()
    scorer = plugin.build_scorer(family_case)
    assert scorer.question_id == family_case["question_id"]
    assert scorer.leaf.leaf_id == "steer_answer_key"


def test_build_scorer_rejects_a_source_sha256_mismatch() -> None:
    plugin, family_case, _state, _phase = _prepared()
    mutated = {**family_case, "source_sha256": "0" * 64}
    with pytest.raises(ValueError, match="source_sha256 does not match"):
        plugin.build_scorer(mutated)


def test_build_reference_providers_and_generator_are_empty() -> None:
    plugin, family_case, _state, _phase = _prepared()
    assert plugin.build_reference_providers(family_case) == ()
    assert plugin.generator(family_case) is None


# ---------------------------------------------------------------------------
# Full episode through the real kernel scheduler (no scoring involved yet).
# ---------------------------------------------------------------------------


def test_scripted_episode_runs_end_to_end_through_the_kernel_scheduler() -> None:
    import asyncio

    element = "borda_count"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    cell = _cell(case)
    plugin = _plugin()

    async def respond(request):
        assert request.seat_id == "agent"
        assert request.observation_schema == "steer_question_observation_v1"
        assert request.action_schema == "steer_option_choice_v1"
        return json.dumps({"option_id": 0})

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=respond)
    )
    assert result.outcome["termination_reason"] == "answered"
    assert result.outcome["selected_option_id"] == 0
    assert result.outcome["failure_code"] is None
    assert result.logical_action_count == 1


def test_scripted_episode_surfaces_an_illegal_option_as_error_not_a_crash() -> None:
    import asyncio

    element = "borda_count"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    cell = _cell(case)
    plugin = _plugin()
    out_of_range = case.payload["options_count"]

    async def respond(request):
        del request
        return json.dumps({"option_id": out_of_range})

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=respond)
    )
    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "option_id_out_of_range"
    assert result.outcome["selected_option_id"] is None


def test_scripted_episode_surfaces_malformed_prose_as_error_not_a_crash() -> None:
    import asyncio

    element = "borda_count"
    question_id = _first_admitted_question_id(element)
    case = _case(element, question_id)
    cell = _cell(case)
    plugin = _plugin()

    async def respond(request):
        del request
        return "I think it's the second one."

    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=plugin, response_source=respond)
    )
    assert result.outcome["termination_reason"] == "error"
    assert result.outcome["failure_code"] == "malformed_answer_json"
