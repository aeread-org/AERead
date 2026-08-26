from __future__ import annotations

from collections.abc import Callable
import hashlib
import inspect
import json

import aeread.sdk.v1 as sdk_v1
import pytest
from pydantic import TypeAdapter, ValidationError, create_model

from aeread.sdk.v1 import (
    ArtifactRef,
    EpisodeAttemptPolicySpec,
    EpisodeTerminalDispositionRule,
    EvaluatorAgentJudgmentTemplateSpec,
    ExecutionBlockSpec,
    ExecutionDesignSpec,
    ExecutionRecordRef,
    FixedPanelResolutionTemplateSpec,
    ImplementationRef,
    ImportedHumanJudgmentTemplateSpec,
    JudgmentWorkTemplateSpec,
    PanelResolutionTemplateSpec,
    SampledPanelResolutionTemplateSpec,
    content_sha256,
)


EXECUTION_DESIGN_EXPORTS = {
    "EpisodeAttemptPolicySpec",
    "EpisodeTerminalDispositionRule",
    "EvaluatorAgentJudgmentTemplateSpec",
    "ExecutionBlockSpec",
    "ExecutionDesignSpec",
    "ExecutionRecordRef",
    "FixedPanelResolutionTemplateSpec",
    "ImportedHumanJudgmentTemplateSpec",
    "JudgmentWorkTemplateSpec",
    "PanelResolutionTemplateSpec",
    "SampledPanelResolutionTemplateSpec",
}

TERMINAL_MAPPING = (
    ("preflight_rejected", "close_run_control_failure"),
    ("predeclared_population_ineligible", "typed_zero_attempt_exclusion"),
    ("execution_not_started", "successor_if_policy_allows"),
    ("isolated_cow_failed_no_publish", "successor_if_policy_allows"),
    (
        "idempotent_same_operation_proven_not_committed",
        "successor_same_operation_if_policy_allows",
    ),
    ("transition_outcome_unknown", "quarantine"),
    ("committed_valid_economic_outcome", "close_valid"),
    (
        "committed_outcome_measurement_failed",
        "close_invalid_without_economic_rerun",
    ),
    ("run_cancelled_proven_no_commit", "close_invalid"),
    ("run_cancelled_commit_unknown", "quarantine"),
)

UNSEEDED_COORDINATES = (
    "population_unit_id",
    "case_id",
    "repetition_index",
    "world_seed",
)
SEEDED_COORDINATES = (
    "population_unit_id",
    "case_id",
    "repetition_index",
    "rollout_seed",
    "world_seed",
)


def _implementation(digit: str = "a", **overrides: object) -> ImplementationRef:
    values: dict[str, object] = {
        "implementation_id": "typed-eligibility-v1",
        "version": "1.0.0",
        "content_sha256": digit * 64,
    }
    values.update(overrides)
    return ImplementationRef.model_validate(values)


def _artifact(digit: str = "b", **overrides: object) -> ArtifactRef:
    values: dict[str, object] = {
        "sha256": digit * 64,
        "media_type": "application/json",
        "size_bytes": 128,
    }
    values.update(overrides)
    return ArtifactRef.model_validate(values)


def _ref(
    ref_kind: str = "agent_profile", *, digit: str = "c", **overrides: object
) -> ExecutionRecordRef:
    values: dict[str, object] = {
        "spec_version": "aeread.execution_record_ref/0.1",
        "record_type": "execution_record_ref",
        "ref_kind": ref_kind,
        "record_id": f"{ref_kind}-v1",
        "record_version": "1.0.0",
        "content_sha256": digit * 64,
    }
    values.update(overrides)
    return ExecutionRecordRef.model_validate(values)


def _fixed_resolution(**overrides: object) -> FixedPanelResolutionTemplateSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.panel_resolution_template/0.1",
        "record_type": "panel_resolution_template",
        "resolution_kind": "fixed_panel",
        "panel_ref": _ref("panel_design", digit="d"),
        "realization_key": "fixed-panel-realization-v1",
        "realization_coupling": "fixed_exact",
        "resolution_source": "selected_unit_ids_from_pinned_fixed_panel",
        "resolution_timing": "before_first_episode_side_effect",
        "failure_rule": "admission_failure_no_retry",
    }
    values.update(overrides)
    return FixedPanelResolutionTemplateSpec.model_validate(values)


def _sampled_resolution(
    *, imported: bool = False, independent: bool = False, **overrides: object
) -> SampledPanelResolutionTemplateSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.panel_resolution_template/0.1",
        "record_type": "panel_resolution_template",
        "resolution_kind": "sampled_panel",
        "panel_ref": _ref("panel_design", digit="e"),
        "realization_key": "sampled-panel-realization-v1",
        "realization_coupling": (
            "independent_rng_domain" if independent else "shared_exact_key"
        ),
        "rng_domain": "candidate-arm" if independent else None,
        "rng_domain_rule": ("sha256_uint64_be_v1" if independent else "not_applicable"),
        "realization_source": (
            "import_predeclared_realization_artifact"
            if imported
            else "execute_pinned_design"
        ),
        "imported_realization_ref": _artifact("f") if imported else None,
        "imported_realization_schema": (
            "aeread.sampled_panel_realization/0.1" if imported else None
        ),
        "import_validator": _implementation("1") if imported else None,
        "resolution_timing": "before_first_episode_side_effect",
        "failure_rule": "admission_failure_no_retry",
        "realization_binding_rule": (
            "bind_frame_design_algorithm_protocol_selected_ids_and_provenance"
        ),
        "publication_rule": "atomic_idempotent_same_key_same_bytes",
    }
    values.update(overrides)
    return SampledPanelResolutionTemplateSpec.model_validate(values)


def _block(
    block_id: str = "block-a",
    *,
    judgment_template_id: str | None = None,
    seeded: bool = False,
    **overrides: object,
) -> ExecutionBlockSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.execution_block/0.1",
        "record_type": "execution_block",
        "block_id": block_id,
        "block_version": "1.0.0",
        "measurement_selection_ref": _ref("measurement_selection", digit="2"),
        "role_ids": ("buyer", "seller"),
        "subject_roles": ("buyer",),
        "profile_ref_by_role": {
            "buyer": _ref("agent_profile", digit="3"),
            "seller": _ref("agent_profile", digit="4"),
        },
        "planned_coordinate_fields": (
            SEEDED_COORDINATES if seeded else UNSEEDED_COORDINATES
        ),
        "judgment_template_id": judgment_template_id,
    }
    values.update(overrides)
    return ExecutionBlockSpec.model_validate(values)


def _evaluator_template(
    *, replacement: bool = False, **overrides: object
) -> EvaluatorAgentJudgmentTemplateSpec:
    slots = ("judge-1", "judge-2")
    values: dict[str, object] = {
        "spec_version": "aeread.judgment_work_template/0.1",
        "record_type": "judgment_work_template",
        "judgment_source_kind": "evaluator_agent",
        "template_id": "template-a",
        "template_version": "1.0.0",
        "local_slot_keys": slots,
        "primary_profile_ref_by_slot": {
            "judge-1": _ref("agent_profile", digit="5"),
            "judge-2": _ref("agent_profile", digit="6"),
        },
        "replacement_rule": (
            "predeclared_outcome_blind_successor_profiles" if replacement else "none"
        ),
        "replacement_profile_refs_by_slot": {
            "judge-1": (_ref("agent_profile", digit="7"),) if replacement else (),
            "judge-2": (_ref("agent_profile", digit="8"),) if replacement else (),
        },
        "replacement_eligibility": _implementation("9") if replacement else None,
        "replacement_eligibility_input_rule": (
            "typed_operational_failure_without_accepted_terminal_result_only"
            if replacement
            else "not_applicable"
        ),
        "assignment_rule": "exact_predeclared_profile_per_local_slot",
        "lease_subject_template": (
            "run_plan_cell_measurement_judgment_slot_and_profile"
        ),
        "materialization_timing": (
            "after_economic_outcome_before_final_episode_evidence_seal"
        ),
    }
    values.update(overrides)
    return EvaluatorAgentJudgmentTemplateSpec.model_validate(values)


def _human_template(**overrides: object) -> ImportedHumanJudgmentTemplateSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.judgment_work_template/0.1",
        "record_type": "judgment_work_template",
        "judgment_source_kind": "imported_human",
        "template_id": "template-human",
        "template_version": "1.0.0",
        "local_slot_keys": ("human-1", "human-2"),
        "source_binding_rule": (
            "exact_resolved_rater_source_in_canonical_local_slot_order"
        ),
        "assignment_rule": "predeclared_import_slot_order",
        "lease_subject_template": "none",
        "materialization_timing": (
            "after_economic_outcome_before_final_episode_evidence_seal"
        ),
    }
    values.update(overrides)
    return ImportedHumanJudgmentTemplateSpec.model_validate(values)


def _terminal_rule(
    terminal_class: str, disposition: str
) -> EpisodeTerminalDispositionRule:
    return EpisodeTerminalDispositionRule.model_validate(
        {
            "spec_version": "aeread.episode_terminal_disposition_rule/0.1",
            "record_type": "episode_terminal_disposition_rule",
            "terminal_class": terminal_class,
            "disposition": disposition,
        }
    )


def _terminal_rules() -> tuple[EpisodeTerminalDispositionRule, ...]:
    return tuple(_terminal_rule(*row) for row in TERMINAL_MAPPING)


def _policy(**overrides: object) -> EpisodeAttemptPolicySpec:
    values: dict[str, object] = {
        "spec_version": "aeread.episode_attempt_policy/0.1",
        "record_type": "episode_attempt_policy",
        "policy_id": "outcome-blind-attempt-policy",
        "policy_version": "1.0.0",
        "max_episode_attempts": 2,
        "terminal_rules": _terminal_rules(),
        "successor_eligibility": _implementation("a"),
        "population_eligibility": _implementation("b"),
        "successor_eligibility_input_rule": (
            "preoutcome_plan_and_typed_terminal_evidence_only"
        ),
        "population_eligibility_input_rule": (
            "preoutcome_population_frame_and_unit_only"
        ),
        "unknown_transition_rule": "quarantine_without_successor",
        "economic_outcome_rerun_rule": "never_rerun_committed_economic_outcome",
        "cancellation_proof_rule": (
            "typed_proven_no_commit_or_typed_commit_unknown_only"
        ),
        "first_attempt_estimand_rule": "preserve_first_attempt_separately",
        "policy_assisted_estimand_rule": (
            "report_policy_assisted_final_without_overwriting_first_attempt"
        ),
    }
    values.update(overrides)
    return EpisodeAttemptPolicySpec.model_validate(values)


def _design(*, with_judge: bool = True, **overrides: object) -> ExecutionDesignSpec:
    template = _evaluator_template() if with_judge else None
    values: dict[str, object] = {
        "spec_version": "aeread.execution_design/0.1",
        "record_type": "execution_design",
        "execution_design_id": "candidate-and-control-v1",
        "execution_design_version": "1.0.0",
        "population_ref": _ref("sampling_population", digit="c"),
        "panel_resolution": _fixed_resolution(),
        "replication_ref": _ref("episode_replication_design", digit="d"),
        "blocks": (
            _block(
                "block-a",
                judgment_template_id=template.template_id if template else None,
            ),
            _block("block-b"),
        ),
        "judgment_templates": (template,) if template else (),
        "episode_attempt_policy": _policy(),
        "cell_expansion_rule": (
            "resolve_exact_population_panel_replication_block_seat_coordinate_product"
        ),
        "execution_hash_domain": "aeread.execution_design/1",
    }
    values.update(overrides)
    return ExecutionDesignSpec.model_validate(values)


def test_execution_design_public_surface_is_exactly_additive() -> None:
    assert EXECUTION_DESIGN_EXPORTS <= set(sdk_v1.__all__)
    assert len(sdk_v1.__all__) == len(set(sdk_v1.__all__)) == 184


def test_execution_design_fields_are_in_exact_canonical_order() -> None:
    assert tuple(ExecutionRecordRef.model_fields) == (
        "spec_version",
        "record_type",
        "ref_kind",
        "record_id",
        "record_version",
        "content_sha256",
    )
    assert tuple(ExecutionBlockSpec.model_fields) == (
        "spec_version",
        "record_type",
        "block_id",
        "block_version",
        "measurement_selection_ref",
        "role_ids",
        "subject_roles",
        "profile_ref_by_role",
        "planned_coordinate_fields",
        "judgment_template_id",
    )
    assert tuple(ExecutionDesignSpec.model_fields) == (
        "spec_version",
        "record_type",
        "execution_design_id",
        "execution_design_version",
        "population_ref",
        "panel_resolution",
        "replication_ref",
        "blocks",
        "judgment_templates",
        "episode_attempt_policy",
        "cell_expansion_rule",
        "execution_hash_domain",
    )


def test_resolution_and_judgment_unions_are_discriminated_and_normalize_dicts() -> None:
    resolution_schema = TypeAdapter(PanelResolutionTemplateSpec).json_schema()
    judgment_schema = TypeAdapter(JudgmentWorkTemplateSpec).json_schema()
    assert resolution_schema["discriminator"]["propertyName"] == "resolution_kind"
    assert judgment_schema["discriminator"]["propertyName"] == "judgment_source_kind"
    assert (
        type(
            TypeAdapter(PanelResolutionTemplateSpec).validate_python(
                _sampled_resolution().model_dump(mode="python")
            )
        )
        is SampledPanelResolutionTemplateSpec
    )
    assert (
        type(
            TypeAdapter(JudgmentWorkTemplateSpec).validate_python(
                _human_template().model_dump(mode="python")
            )
        )
        is ImportedHumanJudgmentTemplateSpec
    )


@pytest.mark.parametrize(
    "kind",
    [
        "sampling_population",
        "panel_design",
        "episode_replication_design",
        "measurement_selection",
        "agent_profile",
    ],
)
def test_all_closed_execution_ref_kinds_are_valid(kind: str) -> None:
    assert _ref(kind).ref_kind == kind


@pytest.mark.parametrize("bad", ["", " "])
def test_execution_ref_rejects_blank_record_id(bad: str) -> None:
    with pytest.raises(ValidationError, match="record_id"):
        _ref(record_id=bad)


@pytest.mark.parametrize("bad", ["", " ", "latest", "1", "1.0"])
def test_execution_ref_rejects_nonsemantic_version(bad: str) -> None:
    with pytest.raises(ValidationError, match="record_version"):
        _ref(record_version=bad)


@pytest.mark.parametrize("digest", ["a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_execution_ref_requires_lowercase_sha256(digest: str) -> None:
    with pytest.raises(ValidationError, match="content_sha256"):
        _ref(content_sha256=digest)


@pytest.mark.parametrize(
    "factory",
    [
        _fixed_resolution,
        _sampled_resolution,
        lambda **kw: _sampled_resolution(imported=True, **kw),
        lambda **kw: _sampled_resolution(independent=True, **kw),
    ],
)
def test_panel_resolution_valid_arms_round_trip(
    factory: Callable[..., object],
) -> None:
    record = factory()
    assert (
        TypeAdapter(PanelResolutionTemplateSpec).validate_python(
            record.model_dump(mode="python")
        )
        == record
    )


@pytest.mark.parametrize("factory", [_fixed_resolution, _sampled_resolution])
def test_panel_resolution_requires_panel_ref_and_nonblank_key(
    factory: Callable[..., object],
) -> None:
    with pytest.raises(ValidationError, match="panel_ref"):
        factory(panel_ref=_ref("sampling_population"))
    with pytest.raises(ValidationError, match="realization_key"):
        factory(realization_key=" ")


@pytest.mark.parametrize(
    "overrides",
    [
        {"rng_domain": "arm-a"},
        {"rng_domain_rule": "sha256_uint64_be_v1"},
        {
            "realization_coupling": "independent_rng_domain",
            "rng_domain": None,
            "rng_domain_rule": "sha256_uint64_be_v1",
        },
        {
            "realization_coupling": "independent_rng_domain",
            "rng_domain": " ",
            "rng_domain_rule": "sha256_uint64_be_v1",
        },
        {
            "realization_coupling": "independent_rng_domain",
            "rng_domain": "arm-a",
            "rng_domain_rule": "not_applicable",
        },
    ],
)
def test_sampled_resolution_rejects_contradictory_coupling(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="rng_domain|coupling"):
        _sampled_resolution(**overrides)


@pytest.mark.parametrize(
    "field_name",
    ["imported_realization_ref", "imported_realization_schema", "import_validator"],
)
def test_execute_source_rejects_each_import_field(field_name: str) -> None:
    values: dict[str, object] = {
        "imported_realization_ref": _artifact(),
        "imported_realization_schema": "aeread.sampled_panel_realization/0.1",
        "import_validator": _implementation(),
    }
    with pytest.raises(ValidationError, match="execute_pinned_design|import"):
        _sampled_resolution(**{field_name: values[field_name]})


@pytest.mark.parametrize(
    "field_name",
    ["imported_realization_ref", "imported_realization_schema", "import_validator"],
)
def test_import_source_requires_all_import_fields(field_name: str) -> None:
    payload = _sampled_resolution(imported=True).model_dump(mode="python")
    payload[field_name] = None
    with pytest.raises(ValidationError, match="import"):
        SampledPanelResolutionTemplateSpec.model_validate(payload)


def test_import_source_requires_exact_complete_artifact_and_implementation() -> None:
    class LooseArtifact(ArtifactRef):
        sha256: str

    class LooseImplementation(ImplementationRef):
        content_sha256: str

    with pytest.raises(ValidationError, match="imported_realization_ref"):
        _sampled_resolution(
            imported=True,
            imported_realization_ref=LooseArtifact(
                sha256="not-a-digest", media_type="application/json", size_bytes=1
            ),
        )
    with pytest.raises(ValidationError, match="import_validator"):
        _sampled_resolution(
            imported=True,
            import_validator=LooseImplementation(
                implementation_id="loose", version="1.0.0", content_sha256="no"
            ),
        )


def test_panel_union_rejects_mixed_arm_and_copied_realized_payload() -> None:
    mixed = _sampled_resolution().model_dump(mode="python")
    mixed["resolution_kind"] = "fixed_panel"
    with pytest.raises(ValidationError):
        TypeAdapter(PanelResolutionTemplateSpec).validate_python(mixed)
    for forbidden in ("selected_unit_ids", "effective_seed", "realized_provenance"):
        with pytest.raises(ValidationError, match="Extra inputs"):
            SampledPanelResolutionTemplateSpec.model_validate(
                {
                    **_sampled_resolution().model_dump(mode="python"),
                    forbidden: ("case-1",),
                }
            )


def test_execution_blocks_accept_both_exact_coordinate_projections() -> None:
    assert _block().planned_coordinate_fields == UNSEEDED_COORDINATES
    assert _block(seeded=True).planned_coordinate_fields == SEEDED_COORDINATES


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("role_ids", ()),
        ("role_ids", ("buyer", "buyer")),
        ("role_ids", ("seller", "buyer")),
        ("subject_roles", ()),
        ("subject_roles", ("seller", "buyer")),
        ("subject_roles", ("buyer", "buyer")),
        ("subject_roles", ("observer",)),
        (
            "planned_coordinate_fields",
            ("case_id", "population_unit_id", "repetition_index", "world_seed"),
        ),
        (
            "planned_coordinate_fields",
            ("population_unit_id", "case_id", "world_seed"),
        ),
    ],
)
def test_execution_block_rejects_role_or_coordinate_errors(
    field_name: str, bad_value: object
) -> None:
    with pytest.raises(ValidationError, match="role|subject|coordinate"):
        _block(**{field_name: bad_value})


def test_execution_block_requires_exact_measurement_and_profile_ref_kinds() -> None:
    with pytest.raises(ValidationError, match="measurement_selection_ref"):
        _block(measurement_selection_ref=_ref("agent_profile"))
    with pytest.raises(ValidationError, match="profile_ref_by_role"):
        _block(
            profile_ref_by_role={
                "buyer": _ref("measurement_selection"),
                "seller": _ref("agent_profile"),
            }
        )


@pytest.mark.parametrize(
    "profile_map",
    [
        {"buyer": _ref("agent_profile")},
        {
            "buyer": _ref("agent_profile"),
            "seller": _ref("agent_profile"),
            "observer": _ref("agent_profile"),
        },
    ],
)
def test_execution_block_profile_keys_exactly_match_roles(
    profile_map: dict[str, ExecutionRecordRef],
) -> None:
    with pytest.raises(ValidationError, match="profile_ref_by_role"):
        _block(profile_ref_by_role=profile_map)


def test_execution_block_rejects_blank_id_version_and_present_template_id() -> None:
    for field_name, bad in (
        ("block_id", " "),
        ("block_version", "latest"),
        ("judgment_template_id", " "),
    ):
        with pytest.raises(ValidationError, match=field_name):
            _block(**{field_name: bad})


@pytest.mark.parametrize("factory", [_evaluator_template, _human_template])
@pytest.mark.parametrize(
    "slot_keys", [(), ("judge-1", "judge-1"), ("judge-2", "judge-1")]
)
def test_judgment_templates_require_nonempty_canonical_unique_slots(
    factory: Callable[..., object], slot_keys: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError, match="local_slot_keys"):
        factory(local_slot_keys=slot_keys)


@pytest.mark.parametrize("factory", [_evaluator_template, _human_template])
def test_both_judgment_arms_require_nonblank_id_and_semantic_version(
    factory: Callable[..., object],
) -> None:
    with pytest.raises(ValidationError, match="template_id"):
        factory(template_id=" ")
    for bad_version in ("", "latest", "1", "1.0", "01.0.0"):
        with pytest.raises(ValidationError, match="template_version"):
            factory(template_version=bad_version)


def test_evaluator_template_maps_exactly_cover_slots_and_use_profile_refs() -> None:
    for field_name, value in (
        (
            "primary_profile_ref_by_slot",
            {"judge-1": _ref("agent_profile")},
        ),
        (
            "replacement_profile_refs_by_slot",
            {"judge-1": (), "judge-2": (), "judge-3": ()},
        ),
        (
            "primary_profile_ref_by_slot",
            {
                "judge-1": _ref("measurement_selection"),
                "judge-2": _ref("agent_profile"),
            },
        ),
    ):
        with pytest.raises(ValidationError, match="profile_ref.*by_slot"):
            _evaluator_template(**{field_name: value})


def test_no_replacement_mode_requires_empty_chains_and_no_eligibility() -> None:
    with pytest.raises(ValidationError, match="replacement"):
        _evaluator_template(
            replacement_profile_refs_by_slot={
                "judge-1": (_ref("agent_profile", digit="d"),),
                "judge-2": (),
            }
        )
    with pytest.raises(ValidationError, match="replacement_eligibility"):
        _evaluator_template(replacement_eligibility=_implementation())
    with pytest.raises(ValidationError, match="replacement_eligibility_input_rule"):
        _evaluator_template(
            replacement_eligibility_input_rule=(
                "typed_operational_failure_without_accepted_terminal_result_only"
            )
        )


def test_successor_mode_requires_chain_pin_and_typed_input_rule() -> None:
    for overrides in (
        {"replacement_profile_refs_by_slot": {"judge-1": (), "judge-2": ()}},
        {"replacement_eligibility": None},
        {"replacement_eligibility_input_rule": "not_applicable"},
    ):
        with pytest.raises(ValidationError, match="replacement"):
            _evaluator_template(replacement=True, **overrides)


def test_successor_chains_reject_primary_or_duplicate_profiles() -> None:
    primary = _evaluator_template().primary_profile_ref_by_slot["judge-1"]
    duplicate = _ref("agent_profile", digit="7")
    for chain in ((primary,), (duplicate, duplicate)):
        with pytest.raises(ValidationError, match="replacement"):
            _evaluator_template(
                replacement=True,
                replacement_profile_refs_by_slot={
                    "judge-1": chain,
                    "judge-2": (_ref("agent_profile", digit="8"),),
                },
            )


@pytest.mark.parametrize("terminal_class,disposition", TERMINAL_MAPPING)
def test_terminal_rule_accepts_only_its_exact_disposition(
    terminal_class: str, disposition: str
) -> None:
    assert _terminal_rule(terminal_class, disposition).disposition == disposition
    all_dispositions = tuple(dict.fromkeys(value for _, value in TERMINAL_MAPPING))
    for wrong in all_dispositions:
        if wrong != disposition:
            with pytest.raises(ValidationError, match="terminal_class|disposition"):
                _terminal_rule(terminal_class, wrong)


@pytest.mark.parametrize("max_attempts", [1, 4])
def test_attempt_policy_accepts_complete_table_and_attempt_bounds(
    max_attempts: int,
) -> None:
    assert (
        _policy(max_episode_attempts=max_attempts).max_episode_attempts == max_attempts
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda rules: rules[:-1],
        lambda rules: rules + (rules[0],),
        lambda rules: (rules[1], rules[0], *rules[2:]),
    ],
)
def test_attempt_policy_rejects_missing_duplicate_or_reordered_table(
    mutator: Callable[[tuple[EpisodeTerminalDispositionRule, ...]], tuple[object, ...]],
) -> None:
    with pytest.raises(ValidationError, match="terminal_rules"):
        _policy(terminal_rules=mutator(_terminal_rules()))


def test_attempt_policy_requires_identity_and_exact_implementation_pins() -> None:
    for field_name, bad in (("policy_id", " "), ("policy_version", "latest")):
        with pytest.raises(ValidationError, match=field_name):
            _policy(**{field_name: bad})

    class LooseImplementation(ImplementationRef):
        content_sha256: str

    loose = LooseImplementation(
        implementation_id="loose", version="1.0.0", content_sha256="not-a-digest"
    )
    for field_name in ("successor_eligibility", "population_eligibility"):
        with pytest.raises(ValidationError, match=field_name):
            _policy(**{field_name: loose})


def test_execution_design_accepts_nonjudge_and_judge_shapes() -> None:
    assert _design(with_judge=False).judgment_templates == ()
    judge_design = _design()
    assert judge_design.blocks[0].judgment_template_id == "template-a"
    assert judge_design.judgment_templates[0].template_id == "template-a"


def test_execution_design_requires_exact_top_level_ref_kinds() -> None:
    for field_name, bad_ref in (
        ("population_ref", _ref("panel_design")),
        ("replication_ref", _ref("sampling_population")),
    ):
        with pytest.raises(ValidationError, match=field_name):
            _design(**{field_name: bad_ref})


def test_execution_design_requires_nonblank_id_and_semantic_version() -> None:
    with pytest.raises(ValidationError, match="execution_design_id"):
        _design(execution_design_id=" ")
    for bad_version in ("", "latest", "1", "1.0", "01.0.0"):
        with pytest.raises(ValidationError, match="execution_design_version"):
            _design(execution_design_version=bad_version)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("blocks", ()),
        ("blocks", (_block("block-b"), _block("block-a"))),
        (
            "judgment_templates",
            (_human_template(template_id="template-z"), _evaluator_template()),
        ),
        ("judgment_templates", (_evaluator_template(), _evaluator_template())),
    ],
)
def test_execution_design_rejects_empty_duplicate_or_reordered_children(
    field_name: str, bad_value: object
) -> None:
    with pytest.raises(ValidationError, match="blocks|judgment_templates"):
        _design(**{field_name: bad_value})


def test_execution_design_requires_exact_template_reference_coverage() -> None:
    with pytest.raises(ValidationError, match="judgment_template"):
        _design(
            blocks=(_block("block-a", judgment_template_id="unknown-template"),),
            judgment_templates=(_evaluator_template(),),
        )
    with pytest.raises(ValidationError, match="judgment_template"):
        _design(
            blocks=(_block("block-a"),),
            judgment_templates=(_evaluator_template(),),
        )
    with pytest.raises(ValidationError, match="judgment_template"):
        _design(
            blocks=(_block("block-a", judgment_template_id="template-a"),),
            judgment_templates=(),
        )


def test_raw_dict_round_trip_is_canonical_and_hash_stable() -> None:
    design = _design()
    dumped = design.model_dump(mode="python")
    reconstructed = ExecutionDesignSpec.model_validate(
        dict(reversed(tuple(dumped.items())))
    )
    assert type(reconstructed) is ExecutionDesignSpec
    assert type(reconstructed.panel_resolution) is FixedPanelResolutionTemplateSpec
    assert type(reconstructed.blocks[0]) is ExecutionBlockSpec
    assert type(reconstructed.judgment_templates[0]) is (
        EvaluatorAgentJudgmentTemplateSpec
    )
    assert content_sha256(reconstructed) == content_sha256(design)


def test_every_concrete_record_requires_every_declared_field() -> None:
    records = (
        _ref(),
        _fixed_resolution(),
        _sampled_resolution(),
        _block(),
        _evaluator_template(),
        _human_template(),
        _terminal_rules()[0],
        _policy(),
        _design(),
    )
    for record in records:
        payload = record.model_dump(mode="python")
        for field_name in type(record).model_fields:
            missing = dict(payload)
            del missing[field_name]
            with pytest.raises(ValidationError):
                type(record).model_validate(missing)


def test_every_concrete_record_rejects_wrong_spec_and_record_literals() -> None:
    records = (
        _ref(),
        _fixed_resolution(),
        _sampled_resolution(),
        _block(),
        _evaluator_template(),
        _human_template(),
        _terminal_rules()[0],
        _policy(),
        _design(),
    )
    for record in records:
        payload = record.model_dump(mode="python")
        for field_name in ("spec_version", "record_type"):
            invalid = {**payload, field_name: "wrong-literal"}
            with pytest.raises(ValidationError, match=field_name):
                type(record).model_validate(invalid)


def test_typed_ref_fields_reject_bare_digest_substitution() -> None:
    with pytest.raises(ValidationError, match="panel_ref"):
        _fixed_resolution(panel_ref="a" * 64)
    with pytest.raises(ValidationError, match="measurement_selection_ref"):
        _block(measurement_selection_ref="b" * 64)
    with pytest.raises(ValidationError, match="population_ref"):
        _design(population_ref="c" * 64)


@pytest.mark.parametrize(
    ("alias", "arm"),
    [
        (PanelResolutionTemplateSpec, _sampled_resolution()),
        (JudgmentWorkTemplateSpec, _evaluator_template()),
    ],
)
def test_union_admission_rejects_extended_arms(alias: object, arm: object) -> None:
    extended_type = create_model(
        f"Extended{type(arm).__name__}",
        later_owned=(str, ...),
        __base__=type(arm),
    )
    extended = extended_type(
        **arm.model_dump(mode="python"), later_owned="runtime-state"
    )
    with pytest.raises(ValidationError, match="exact concrete type"):
        TypeAdapter(alias).validate_python(extended)


def test_execution_design_schema_hashes_are_frozen_after_green() -> None:
    def digest(value: object) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    current = {
        "ExecutionRecordRef": digest(ExecutionRecordRef.model_json_schema()),
        "FixedPanelResolutionTemplateSpec": digest(
            FixedPanelResolutionTemplateSpec.model_json_schema()
        ),
        "SampledPanelResolutionTemplateSpec": digest(
            SampledPanelResolutionTemplateSpec.model_json_schema()
        ),
        "PanelResolutionTemplateSpec": digest(
            TypeAdapter(PanelResolutionTemplateSpec).json_schema()
        ),
        "ExecutionBlockSpec": digest(ExecutionBlockSpec.model_json_schema()),
        "EvaluatorAgentJudgmentTemplateSpec": digest(
            EvaluatorAgentJudgmentTemplateSpec.model_json_schema()
        ),
        "ImportedHumanJudgmentTemplateSpec": digest(
            ImportedHumanJudgmentTemplateSpec.model_json_schema()
        ),
        "JudgmentWorkTemplateSpec": digest(
            TypeAdapter(JudgmentWorkTemplateSpec).json_schema()
        ),
        "EpisodeTerminalDispositionRule": digest(
            EpisodeTerminalDispositionRule.model_json_schema()
        ),
        "EpisodeAttemptPolicySpec": digest(
            EpisodeAttemptPolicySpec.model_json_schema()
        ),
        "ExecutionDesignSpec": digest(ExecutionDesignSpec.model_json_schema()),
    }
    assert current == {
        "ExecutionRecordRef": (
            "76c58db574da0979b7ca4d9a20d158d04e689925fd7c6292a3695a8de5fa7b45"
        ),
        "FixedPanelResolutionTemplateSpec": (
            "163c45c58ee9289db31c11211698cf774f34284655f92f74b11337f5e0f94e92"
        ),
        "SampledPanelResolutionTemplateSpec": (
            "a6467be1c2f6d4aaea05af1782b4abfb2895f5becb0887a01273d21d43d38be5"
        ),
        "PanelResolutionTemplateSpec": (
            "d3e1f4420882cfd49c3b5fe74a5ed4de10bb29393c0317120dd6444a73f1403d"
        ),
        "ExecutionBlockSpec": (
            "98edf94ff711eadaea3bdc12070f39819b6e72a6a4070ba4fabbf992425ee754"
        ),
        "EvaluatorAgentJudgmentTemplateSpec": (
            "b28bbfaf9956213feea7c18ff40d3ecb8e8f5a68c758fc014a46dc998033db6a"
        ),
        "ImportedHumanJudgmentTemplateSpec": (
            "6ea9621736a98b5390b5d495b05f13a3cdd0be4218b83c65114ced159bc47934"
        ),
        "JudgmentWorkTemplateSpec": (
            "0e007cd30c02b3ec4b1635a05398b59ddc0cca7c8e552229dce73303212ac1ed"
        ),
        "EpisodeTerminalDispositionRule": (
            "7c88bce065f5881806acb83b6409b48b177e65df5633daf5853db15352b53900"
        ),
        "EpisodeAttemptPolicySpec": (
            "1ed5329ddb2a67c0d8d309d72fbbe7dfa75002ec40720369b166cebd26f0283e"
        ),
        "ExecutionDesignSpec": (
            "eb3238d64afe5e3725cbd4a2335fa6de10b9f8c1eb43573c893bc54cf70a58a3"
        ),
    }


def test_terminal_rule_rejects_subclass_and_requires_dump_revalidation() -> None:
    rule = _terminal_rules()[0]
    extended_type = create_model(
        "ExtendedEpisodeTerminalDispositionRule",
        later_owned=(str, ...),
        __base__=EpisodeTerminalDispositionRule,
    )
    extended = extended_type(
        **rule.model_dump(mode="python"), later_owned="realized-evidence"
    )
    with pytest.raises(ValidationError, match="exact concrete type"):
        EpisodeTerminalDispositionRule.model_validate(extended)

    unchecked = rule.model_copy(update={"disposition": "quarantine"})
    with pytest.raises(ValidationError, match="terminal_class|disposition"):
        EpisodeTerminalDispositionRule.model_validate(
            unchecked.model_dump(mode="python")
        )


@pytest.mark.parametrize(
    ("model_type", "factory"),
    [
        (ExecutionRecordRef, _ref),
        (FixedPanelResolutionTemplateSpec, _fixed_resolution),
        (SampledPanelResolutionTemplateSpec, _sampled_resolution),
        (ExecutionBlockSpec, _block),
        (EvaluatorAgentJudgmentTemplateSpec, _evaluator_template),
        (ImportedHumanJudgmentTemplateSpec, _human_template),
        (EpisodeAttemptPolicySpec, _policy),
        (ExecutionDesignSpec, _design),
    ],
)
def test_concrete_records_reject_normally_constructed_subclasses(
    model_type: type[object], factory: Callable[..., object]
) -> None:
    extended_type = create_model(
        f"Extended{model_type.__name__}",
        later_owned=(str, ...),
        __base__=model_type,
    )
    extended = extended_type(
        **factory().model_dump(mode="python"), later_owned="receipt"
    )
    with pytest.raises(ValidationError, match="exact concrete type"):
        model_type.model_validate(extended)


def test_records_are_frozen_extra_forbid_and_require_dump_revalidation() -> None:
    design = _design()
    with pytest.raises(ValidationError, match="Extra inputs"):
        ExecutionDesignSpec.model_validate(
            {**design.model_dump(mode="python"), "execution_design_sha256": "a" * 64}
        )
    with pytest.raises(ValidationError, match="frozen"):
        design.execution_design_id = "changed"  # type: ignore[misc]
    unchecked = design.model_copy(update={"execution_design_version": "latest"})
    with pytest.raises(ValidationError, match="execution_design_version"):
        ExecutionDesignSpec.model_validate(unchecked.model_dump(mode="python"))


@pytest.mark.parametrize(
    "forbidden",
    [
        "selected_unit_ids",
        "rollout_seeds",
        "evaluation_work",
        "provider_session_id",
        "receipt",
        "attempt_selection_proof",
        "family_action_failure_disposition",
        "analysis_design_sha256",
    ],
)
def test_execution_design_rejects_later_owned_fields(forbidden: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ExecutionDesignSpec.model_validate(
            {**_design().model_dump(mode="python"), forbidden: "forbidden"}
        )


def test_execution_declarations_exclude_forbidden_runtime_and_science_coupling() -> (
    None
):
    forbidden = {
        "analysisrecord",
        "attemptselectionproof",
        "benchmark",
        "clusterdesignspec",
        "evaluationwork",
        "familyactionfailuredisposition",
        "filesystem",
        "network",
        "plancell",
        "providerrequest",
        "rattempt",
        "rateraggregateinput",
        "receipt",
        "reconciliation",
        "runplan",
        "selectionproof",
        "sessiontoken",
    }
    declarations = (
        ExecutionRecordRef,
        FixedPanelResolutionTemplateSpec,
        SampledPanelResolutionTemplateSpec,
        ExecutionBlockSpec,
        EvaluatorAgentJudgmentTemplateSpec,
        ImportedHumanJudgmentTemplateSpec,
        EpisodeTerminalDispositionRule,
        EpisodeAttemptPolicySpec,
        ExecutionDesignSpec,
    )
    surface = "\n".join(
        inspect.getsource(declaration)
        + json.dumps(declaration.model_json_schema(), sort_keys=True)
        for declaration in declarations
    ).lower()
    assert not {token for token in forbidden if token in surface}


@pytest.mark.parametrize(
    ("source_name", "panel", "seeded", "template"),
    [
        ("housing", "fixed", True, "none"),
        ("tau3-db", "fixed", False, "none"),
        ("state-deterministic", "sampled-shared", True, "none"),
        ("econ-scheduling", "sampled-independent", True, "none"),
        ("terms-comparative", "fixed", False, "human"),
        ("gdpval-rater", "fixed", False, "agent"),
    ],
)
def test_representative_sources_only_pressure_authoring_shapes(
    source_name: str, panel: str, seeded: bool, template: str
) -> None:
    panels = {
        "fixed": _fixed_resolution(),
        "sampled-shared": _sampled_resolution(),
        "sampled-independent": _sampled_resolution(independent=True),
    }
    template_record = (
        _human_template()
        if template == "human"
        else _evaluator_template() if template == "agent" else None
    )
    block = _block(
        judgment_template_id=(
            template_record.template_id if template_record is not None else None
        ),
        seeded=seeded,
    )
    design = _design(
        execution_design_id=f"pressure-{source_name}",
        panel_resolution=panels[panel],
        blocks=(block,),
        judgment_templates=(template_record,) if template_record else (),
    )
    assert design.execution_design_id == f"pressure-{source_name}"
