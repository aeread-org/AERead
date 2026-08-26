from __future__ import annotations

from collections.abc import Callable
import hashlib
import inspect
import json

import aeread.sdk.v1 as sdk_v1
import pytest
from pydantic import TypeAdapter, ValidationError, create_model

from aeread.sdk.v1 import (
    EvaluationInstrumentSpec,
    ImplementationRef,
    JudgeEvaluationInstrumentSpec,
    MeasurementSelectionSpec,
    NoJudgeEvaluationInstrumentSpec,
    content_sha256,
)


MEASUREMENT_SELECTION_EXPORTS = {
    "EvaluationInstrumentSpec",
    "JudgeEvaluationInstrumentSpec",
    "MeasurementSelectionSpec",
    "NoJudgeEvaluationInstrumentSpec",
}


def _implementation(**overrides: object) -> ImplementationRef:
    values: dict[str, object] = {
        "implementation_id": "categorical-majority-with-tie",
        "version": "1.0.0",
        "content_sha256": "a" * 64,
    }
    values.update(overrides)
    return ImplementationRef.model_validate(values)


def _no_judge(**overrides: object) -> NoJudgeEvaluationInstrumentSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.evaluation_instrument/0.1",
        "record_type": "evaluation_instrument",
        "instrument_kind": "not_required",
    }
    values.update(overrides)
    return NoJudgeEvaluationInstrumentSpec.model_validate(values)


def _judge(**overrides: object) -> JudgeEvaluationInstrumentSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.evaluation_instrument/0.1",
        "record_type": "evaluation_instrument",
        "instrument_kind": "judge_score",
        "instrument_id": "expert-majority-v1",
        "instrument_version": "1.0.0",
        "aggregation": _implementation(),
        "aggregation_input": ("one_accepted_terminal_result_per_planned_judgment_slot"),
        "slot_coverage_rule": "exact_planned_terminal_slots",
        "minimum_valid_slots": 3,
        "missing_slot_rule": "invalid_measurement",
        "duplicate_slot_rule": "reject",
        "invalid_result_rule": "invalid_measurement",
        "tie_rule": "preserve_valid_categorical_tie",
        "disagreement_preservation_rule": (
            "preserve_all_planned_slot_terminal_result_refs_and_dispositions"
        ),
        "aggregate_result_schema_ref": "aeread.rater_result/0.1",
    }
    values.update(overrides)
    return JudgeEvaluationInstrumentSpec.model_validate(values)


def _selection(
    *,
    evaluation_class: str = "deterministic",
    instrument: object | None = None,
    **overrides: object,
) -> MeasurementSelectionSpec:
    if instrument is None:
        instrument = _judge() if evaluation_class == "judge_dependent" else _no_judge()
    values: dict[str, object] = {
        "spec_version": "aeread.measurement_selection/0.1",
        "record_type": "measurement_selection",
        "selection_id": "selected-leaf",
        "selection_version": "1.0.0",
        "leaf_id": "family-leaf",
        "leaf_version": "1.0.0",
        "leaf_sha256": "b" * 64,
        "selected_evaluation_class": evaluation_class,
        "evaluation_instrument": instrument,
    }
    values.update(overrides)
    return MeasurementSelectionSpec.model_validate(values)


def test_evaluation_instrument_union_is_exactly_discriminated() -> None:
    schema = TypeAdapter(EvaluationInstrumentSpec).json_schema()
    assert schema["discriminator"] == {
        "mapping": {
            "judge_score": "#/$defs/JudgeEvaluationInstrumentSpec",
            "not_required": "#/$defs/NoJudgeEvaluationInstrumentSpec",
        },
        "propertyName": "instrument_kind",
    }
    assert (
        TypeAdapter(EvaluationInstrumentSpec)
        .validate_python(_no_judge().model_dump(mode="python"))
        .__class__
        is NoJudgeEvaluationInstrumentSpec
    )
    assert (
        TypeAdapter(EvaluationInstrumentSpec)
        .validate_python(_judge().model_dump(mode="python"))
        .__class__
        is JudgeEvaluationInstrumentSpec
    )


@pytest.mark.parametrize(
    ("evaluation_class", "instrument_kind"),
    [
        ("deterministic", "not_required"),
        ("stochastic_estimator", "not_required"),
        ("judge_dependent", "judge_score"),
    ],
)
def test_valid_measurement_selections_are_canonical_and_hashable(
    evaluation_class: str, instrument_kind: str
) -> None:
    selection = _selection(evaluation_class=evaluation_class)
    assert selection.evaluation_instrument.instrument_kind == instrument_kind
    dumped = selection.model_dump(mode="python")
    assert MeasurementSelectionSpec.model_validate(dumped) == selection
    assert content_sha256(selection) == content_sha256(
        MeasurementSelectionSpec.model_validate(dict(reversed(tuple(dumped.items()))))
    )


@pytest.mark.parametrize(
    ("evaluation_class", "instrument"),
    [
        ("judge_dependent", _no_judge()),
        ("deterministic", _judge()),
        ("stochastic_estimator", _judge()),
    ],
)
def test_measurement_selection_rejects_class_instrument_mismatch(
    evaluation_class: str, instrument: object
) -> None:
    with pytest.raises(ValidationError, match="evaluation class|instrument"):
        _selection(evaluation_class=evaluation_class, instrument=instrument)


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_judge, "instrument_id"),
        (_judge, "aggregate_result_schema_ref"),
        (_selection, "selection_id"),
        (_selection, "leaf_id"),
    ],
)
@pytest.mark.parametrize("bad_value", ["", " ", "\t"])
def test_measurement_selection_rejects_blank_identifiers(
    factory: Callable[..., object], field_name: str, bad_value: str
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        factory(**{field_name: bad_value})


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_judge, "instrument_version"),
        (_selection, "selection_version"),
        (_selection, "leaf_version"),
    ],
)
@pytest.mark.parametrize("bad_value", ["", "latest", "1", "1.0", "01.0.0"])
def test_measurement_selection_rejects_nonsemantic_or_mutable_versions(
    factory: Callable[..., object], field_name: str, bad_value: str
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        factory(**{field_name: bad_value})


@pytest.mark.parametrize(
    "bad_digest",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64],
)
def test_measurement_selection_rejects_malformed_leaf_digest(
    bad_digest: str,
) -> None:
    with pytest.raises(ValidationError, match="leaf_sha256"):
        _selection(leaf_sha256=bad_digest)


@pytest.mark.parametrize("bad_value", [0, -1, True, "3", 3.0, None, (), {}])
def test_judge_instrument_requires_exact_positive_minimum_slots(
    bad_value: object,
) -> None:
    with pytest.raises(ValidationError, match="minimum_valid_slots"):
        _judge(minimum_valid_slots=bad_value)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("record_type", "judge_instrument"),
        ("spec_version", "aeread.evaluation_instrument/0.2"),
        ("aggregation_input", "accepted_results"),
        ("slot_coverage_rule", "minimum_only"),
        ("missing_slot_rule", "drop"),
        ("duplicate_slot_rule", "deduplicate"),
        ("invalid_result_rule", "drop"),
        ("tie_rule", "coerce_zero"),
        ("disagreement_preservation_rule", "aggregate_only"),
    ],
)
def test_judge_instrument_rejects_wrong_closed_vocabulary(
    field_name: str, bad_value: object
) -> None:
    with pytest.raises(ValidationError):
        _judge(**{field_name: bad_value})


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_no_judge, "spec_version"),
        (_no_judge, "record_type"),
        (_no_judge, "instrument_kind"),
        (_judge, "disagreement_preservation_rule"),
        (_judge, "aggregate_result_schema_ref"),
        (_selection, "selection_id"),
        (_selection, "evaluation_instrument"),
    ],
)
def test_measurement_selection_records_reject_missing_required_fields(
    factory: Callable[..., object], field_name: str
) -> None:
    payload = factory().model_dump(mode="python")
    del payload[field_name]
    with pytest.raises(ValidationError, match=field_name):
        type(factory()).model_validate(payload)


def test_evaluation_instrument_union_rejects_mixed_arm_payloads() -> None:
    mixed = _judge().model_dump(mode="python")
    mixed["instrument_kind"] = "not_required"
    with pytest.raises(ValidationError):
        TypeAdapter(EvaluationInstrumentSpec).validate_python(mixed)


def test_judge_instrument_requires_complete_exact_aggregation_pin() -> None:
    for bad_ref in (
        _implementation(implementation_id=" "),
        _implementation(version="latest"),
    ):
        with pytest.raises(ValidationError, match="aggregation"):
            _judge(aggregation=bad_ref)
    for bad_digest in ("a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ValidationError, match="content_sha256"):
            _implementation(content_sha256=bad_digest)


def test_nested_implementation_ref_requires_exact_base_type() -> None:
    class LooseImplementation(ImplementationRef):
        content_sha256: str

    loose = LooseImplementation(
        implementation_id="categorical-majority-with-tie",
        version="1.0.0",
        content_sha256="not-a-digest",
    )
    with pytest.raises(ValidationError, match="aggregation"):
        _judge(aggregation=loose)


@pytest.mark.parametrize(
    ("model_type", "factory"),
    [
        (NoJudgeEvaluationInstrumentSpec, _no_judge),
        (JudgeEvaluationInstrumentSpec, _judge),
        (MeasurementSelectionSpec, _selection),
    ],
)
def test_concrete_record_admission_rejects_normally_constructed_subclasses(
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


@pytest.mark.parametrize("arm_factory", [_no_judge, _judge])
def test_union_admission_rejects_extended_instrument_arms(
    arm_factory: Callable[..., object],
) -> None:
    arm = arm_factory()
    extended_type = create_model(
        f"Extended{type(arm).__name__}",
        later_owned=(str, ...),
        __base__=type(arm),
    )
    extended = extended_type(**arm.model_dump(mode="python"), later_owned="attempt")
    with pytest.raises(ValidationError, match="exact concrete type"):
        TypeAdapter(EvaluationInstrumentSpec).validate_python(extended)


def test_raw_dict_nesting_normalizes_to_exact_declared_types() -> None:
    payload = _selection(evaluation_class="judge_dependent").model_dump(mode="python")
    selection = MeasurementSelectionSpec.model_validate(payload)
    assert type(selection) is MeasurementSelectionSpec
    assert type(selection.evaluation_instrument) is JudgeEvaluationInstrumentSpec
    assert type(selection.evaluation_instrument.aggregation) is ImplementationRef


def test_records_are_frozen_extra_forbid_and_unchecked_objects_need_revalidation() -> (
    None
):
    selection = _selection()
    with pytest.raises(ValidationError, match="Extra inputs"):
        MeasurementSelectionSpec.model_validate(
            {**selection.model_dump(mode="python"), "receipt_id": "forbidden"}
        )
    with pytest.raises(ValidationError, match="frozen"):
        selection.leaf_id = "changed"  # type: ignore[misc]

    unchecked = selection.model_copy(update={"leaf_sha256": "not-a-digest"})
    assert unchecked.leaf_sha256 == "not-a-digest"
    with pytest.raises(ValidationError, match="leaf_sha256"):
        MeasurementSelectionSpec.model_validate(unchecked.model_dump(mode="python"))

    unchecked_ref = _implementation().model_copy(
        update={"content_sha256": "not-a-digest"}
    )
    unchecked_judge = _judge().model_copy(update={"aggregation": unchecked_ref})
    assert unchecked_judge.aggregation.content_sha256 == "not-a-digest"
    with pytest.raises(ValidationError, match="content_sha256"):
        JudgeEvaluationInstrumentSpec.model_validate(
            unchecked_judge.model_dump(mode="python")
        )


def test_measurement_selection_schema_hashes_are_frozen_after_green() -> None:
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
        "NoJudgeEvaluationInstrumentSpec": digest(
            NoJudgeEvaluationInstrumentSpec.model_json_schema()
        ),
        "JudgeEvaluationInstrumentSpec": digest(
            JudgeEvaluationInstrumentSpec.model_json_schema()
        ),
        "EvaluationInstrumentSpec": digest(
            TypeAdapter(EvaluationInstrumentSpec).json_schema()
        ),
        "MeasurementSelectionSpec": digest(
            MeasurementSelectionSpec.model_json_schema()
        ),
    }
    assert current == {
        "NoJudgeEvaluationInstrumentSpec": (
            "67768cf428cf351b0d6b16ee0d607a74c8c1dead1d482f65d9419fe78ec2db29"
        ),
        "JudgeEvaluationInstrumentSpec": (
            "f514c0995f74a593e142a51f0863166b96a6061e1e1c72302edd99e532c544ac"
        ),
        "EvaluationInstrumentSpec": (
            "d9c1960e1e75ee4d584b500e351bfd87e3370082f613a910c07d5f5e8367d226"
        ),
        "MeasurementSelectionSpec": (
            "371bda54d779eebbf18c64092b08a4c92bb5d6edfee9f0eb93b656be0642370b"
        ),
    }


def test_measurement_selection_declarations_exclude_later_owned_coupling() -> None:
    forbidden = {
        "agentprofile",
        "analysis",
        "artifact view",
        "attemptpolicyevidence",
        "attemptselectionproof",
        "cluster",
        "composition",
        "evaluationblock",
        "evaluationwork",
        "evaluator_profile",
        "estimator_method",
        "filesystem",
        "interval",
        "judgment_slot_id",
        "missingness",
        "multiplicity",
        "network",
        "pairing",
        "panel",
        "plancell",
        "population",
        "provider",
        "rateraggregateinput",
        "raterattempt",
        "receipt",
        "replacement",
        "replication",
        "retry",
        "runplan",
        "session",
        "test",
        "tool",
    }
    declarations = (
        NoJudgeEvaluationInstrumentSpec,
        JudgeEvaluationInstrumentSpec,
        MeasurementSelectionSpec,
    )
    public_surface = "\n".join(
        inspect.getsource(declaration)
        + json.dumps(declaration.model_json_schema(), sort_keys=True)
        for declaration in declarations
    ).lower()
    public_surface += json.dumps(
        TypeAdapter(EvaluationInstrumentSpec).json_schema(), sort_keys=True
    ).lower()
    assert not {token for token in forbidden if token in public_surface}


@pytest.mark.parametrize(
    ("source_name", "evaluation_class", "instrument_kind"),
    [
        ("housing", "deterministic", "not_required"),
        ("tau3-db", "deterministic", "not_required"),
        ("state-deterministic", "deterministic", "not_required"),
        ("econ-scheduling", "stochastic_estimator", "not_required"),
        ("terms-comparative", "stochastic_estimator", "not_required"),
        ("gdpval-rater", "judge_dependent", "judge_score"),
    ],
)
def test_representative_sources_only_pressure_constructor_expression(
    source_name: str, evaluation_class: str, instrument_kind: str
) -> None:
    selection = _selection(
        evaluation_class=evaluation_class,
        selection_id=f"pressure-{source_name}",
    )
    assert selection.selected_evaluation_class == evaluation_class
    assert selection.evaluation_instrument.instrument_kind == instrument_kind


