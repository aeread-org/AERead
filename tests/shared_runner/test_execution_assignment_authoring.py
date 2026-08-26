from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
from typing import Annotated, Literal, get_args

import pytest
from pydantic import Field, TypeAdapter, ValidationError, model_validator

import aeread.sdk.v1 as sdk_v1
import aeread.sdk.v1.base as sdk_base
import aeread.sdk.v1.records as records_module
from aeread.sdk.v1 import (
    ArtifactRef,
    AssignmentAuthoringRecordRef,
    ExchangeabilityDomainSpec,
    ExecuteUniformWithinPairAssignmentSourceSpec,
    ExecutionAssignmentSourceSpec,
    ImplementationRef,
    ImportedUniformWithinPairAssignmentSourceSpec,
    IndependentUniformWithinPairExecutionAssignmentSpec,
    content_sha256,
)


ASSIGNMENT_AUTHORING_EXPORTS = {
    "AssignmentAuthoringRecordRef",
    "ExchangeabilityDomainSpec",
    "ExecuteUniformWithinPairAssignmentSourceSpec",
    "ExecutionAssignmentSourceSpec",
    "ImportedUniformWithinPairAssignmentSourceSpec",
    "IndependentUniformWithinPairExecutionAssignmentSpec",
}

B4B_EXPORTS = {
    "AnalysisSourceRef",
    "EffectiveResamplingBlockSpec",
    "PopulationClusterProjectionSpec",
    "PairProjectionSpec",
    "NoIntervalSpec",
    "ClusterBootstrapStabilityIntervalSpec",
    "IntervalSpec",
    "NoHypothesisTestSpec",
    "PairedRandomizationTestSpec",
    "HypothesisTestSpec",
    "NoMultiplicityAdjustmentSpec",
    "HolmMultiplicityAdjustmentSpec",
    "MultiplicityAdjustmentSpec",
    "InferenceCompatibilitySpec",
}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifact(label: str) -> ArtifactRef:
    return ArtifactRef(
        sha256=_sha(f"artifact:{label}"),
        media_type="application/json",
        size_bytes=len(label) + 1,
    )


def _implementation(label: str) -> ImplementationRef:
    return ImplementationRef(
        implementation_id=f"implementation.{label}",
        version="1.0.0",
        content_sha256=_sha(f"implementation:{label}"),
    )


def _authoring_ref(
    ref_kind: str,
    *,
    record_id: str | None = None,
    record_version: str = "1.0.0",
) -> AssignmentAuthoringRecordRef:
    return AssignmentAuthoringRecordRef(
        spec_version="aeread.assignment_authoring_record_ref/0.1",
        record_type="assignment_authoring_record_ref",
        ref_kind=ref_kind,
        record_id=record_id or f"record.{ref_kind}",
        record_version=record_version,
        content_sha256=_sha(f"record:{ref_kind}:{record_id or 'default'}"),
    )


def _domain(**overrides: object) -> ExchangeabilityDomainSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.exchangeability_domain/0.1",
        "record_type": "exchangeability_domain",
        "domain_id": "domain.paired-policy",
        "domain_version": "1.0.0",
        "domain_artifact_ref": _artifact("domain"),
        "canonical_schema_ref": _artifact("domain-schema"),
        "validator": _implementation("domain-validator"),
        "allocation_unit": "preassignment_pair",
        "eligible_pair_key_rule": "exact_preassignment_pair_set_keys",
        "arm_binding_rule": ("exact_declared_subject_and_comparator_execution_blocks"),
        "exclusion_rule": "predeclared_only_no_post_assignment_or_outcome_exclusion",
        "supported_null": (
            "sharp_no_unit_level_effect_under_declared_within_pair_allocation"
        ),
        "assumption_status": (
            "preregistered_scientific_assumption_not_empirically_proven_by_schema"
        ),
    }
    values.update(overrides)
    return ExchangeabilityDomainSpec.model_validate(values)


def _execute_source(
    **overrides: object,
) -> ExecuteUniformWithinPairAssignmentSourceSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.execution_assignment_source/0.1",
        "record_type": "execution_assignment_source",
        "source_kind": "execute_pinned",
        "algorithm": _implementation("assignment-algorithm"),
        "protocol_ref": _artifact("assignment-protocol"),
        "selection_seed": 0,
        "seed_provenance_ref": _artifact("seed-provenance"),
        "seed_provenance_schema_ref": _artifact("seed-provenance-schema"),
        "seed_provenance_validator": _implementation("seed-provenance-validator"),
        "seed_generation_rule": (
            "uniform_integer_over_exact_n_pair_assignment_vectors_committed_preassignment"
        ),
        "rng_domain": "aeread.independent_uniform_within_pair_assignment/0.1",
        "bit_rule": "n_low_order_seed_bits_in_canonical_pair_order",
        "determinism_rule": (
            "same_claimed_inputs_reproduce_identical_canonical_realization_bytes"
        ),
    }
    values.update(overrides)
    return ExecuteUniformWithinPairAssignmentSourceSpec.model_validate(values)


def _import_source(
    **overrides: object,
) -> ImportedUniformWithinPairAssignmentSourceSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.execution_assignment_source/0.1",
        "record_type": "execution_assignment_source",
        "source_kind": "import_predeclared",
        "realization_artifact_ref": _artifact("realization"),
        "canonical_schema_ref": _artifact("realization-schema"),
        "validator": _implementation("realization-validator"),
        "generation_protocol_ref": _artifact("generation-protocol"),
        "randomization_provenance_ref": _artifact("randomization-provenance"),
        "randomization_provenance_schema_ref": _artifact(
            "randomization-provenance-schema"
        ),
        "randomization_provenance_validator": _implementation(
            "randomization-provenance-validator"
        ),
        "assignment_law": (
            "independent_uniform_one_half_allocation_for_each_exact_preassignment_pair"
        ),
        "registration_rule": (
            "content_pinned_before_plan_cell_publication_and_first_side_effect"
        ),
    }
    values.update(overrides)
    return ImportedUniformWithinPairAssignmentSourceSpec.model_validate(values)


def _assignment(
    *,
    source: object | None = None,
    **overrides: object,
) -> IndependentUniformWithinPairExecutionAssignmentSpec:
    values: dict[str, object] = {
        "spec_version": "aeread.execution_assignment_design/0.1",
        "record_type": "execution_assignment_design",
        "assignment_design_id": "assignment.policy-pair",
        "assignment_design_version": "1.0.0",
        "base_execution_design_ref": _authoring_ref("execution_design"),
        "pairing_ref": _authoring_ref("pairing_design"),
        "exchangeability_domain_ref": _authoring_ref("exchangeability_domain"),
        "subject_execution_block_id": "block.subject",
        "comparator_execution_block_id": "block.comparator",
        "assignment_unit": "pair_key",
        "assignment_mechanism": "independent_uniform_within_pair",
        "allocation_probability_rule": "one_half_each_arm_per_pair",
        "source": source if source is not None else _execute_source(),
        "realization_timing": (
            "before_plan_cell_publication_and_first_execution_side_effect"
        ),
        "pair_coverage_rule": (
            "exact_cover_of_task_1_1c_preassignment_pair_set_no_subset"
        ),
        "reroll_rule": (
            "one_scope_one_claim_one_realization_new_draw_requires_new_suite_version"
        ),
        "scope_derivation_rule": (
            "task_1_1c_derived_not_caller_supplied_excludes_seed_source_design_"
            "provenance_and_realization_bytes"
        ),
        "realization_key_rule": (
            "task_1_1c_derived_from_scope_and_scope_claim_not_caller_supplied"
        ),
        "execution_binding_rule": (
            "resolved_assignment_changes_execution_design_plan_cell_and_receipt_identity"
        ),
    }
    values.update(overrides)
    return IndependentUniformWithinPairExecutionAssignmentSpec.model_validate(values)


def _dump(value: object) -> object:
    return value.model_dump(mode="json")  # type: ignore[attr-defined]


def test_assignment_authoring_schema_and_fixture_hashes_are_frozen() -> None:
    schema_digest = {
        record_type.__name__: hashlib.sha256(
            json.dumps(
                record_type.model_json_schema(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        for record_type in (
            AssignmentAuthoringRecordRef,
            ExchangeabilityDomainSpec,
            ExecuteUniformWithinPairAssignmentSourceSpec,
            ImportedUniformWithinPairAssignmentSourceSpec,
            IndependentUniformWithinPairExecutionAssignmentSpec,
        )
    }
    assert schema_digest == {
        "AssignmentAuthoringRecordRef": (
            "219be70103138c0e70825dd5950bb6cb85d9a640a6b5eb2b57deae460003b791"
        ),
        "ExchangeabilityDomainSpec": (
            "17673f0b39efb5733ed35bbc7084696bebd198b0ac3e9197df729578864608b0"
        ),
        "ExecuteUniformWithinPairAssignmentSourceSpec": (
            "8c9a0f0d213bbe53ced5bae4e5ec7c878227bd12d6dbb8f189da5c16978b02ae"
        ),
        "ImportedUniformWithinPairAssignmentSourceSpec": (
            "bce398f63b8c58d2ce7444a0a73f842983b857367eaded07952d2a091ad4d7bb"
        ),
        "IndependentUniformWithinPairExecutionAssignmentSpec": (
            "e669bc849b0d4b5390b0472c50df9eb548c27feaf8122fee71fd85678ee93c22"
        ),
    }
    assert {
        "ref": content_sha256(_authoring_ref("execution_design")),
        "domain": content_sha256(_domain()),
        "execute": content_sha256(_execute_source()),
        "import": content_sha256(_import_source()),
        "assignment_execute": content_sha256(_assignment()),
        "assignment_import": content_sha256(_assignment(source=_import_source())),
    } == {
        "ref": "8b44d23c01f57657b4c1f8a46547d231e3a730719472feb4d939dc93342ec797",
        "domain": "c82c1398cd787712557094e7e8dec6e7236168504e79494bdbd6a2bb8153cf26",
        "execute": "848d5ab9cea63864549c5d68ec1755d147548493b72d3e15e00f0bcdad9feba6",
        "import": "894914aa578b41dca785458040a0fd30b74a6d268cf8d57c6e13ab3fc124024f",
        "assignment_execute": (
            "8f69edb82c633afa16161f188046473454015099faccb4bf6b9c10b1537cdd20"
        ),
        "assignment_import": (
            "3e92fb804d57325e556b874db9c450c53193562837d1170c9e818ba6174febe1"
        ),
    }


@pytest.mark.parametrize("source", [_execute_source(), _import_source()])
def test_valid_sources_and_assignments_round_trip_canonically(source: object) -> None:
    adapter = TypeAdapter(ExecutionAssignmentSourceSpec)
    source_dump = _dump(source)
    resolved = adapter.validate_python(source_dump)
    assert type(resolved) is type(source)
    assert _dump(resolved) == source_dump

    assignment = _assignment(source=source_dump)
    restored = IndependentUniformWithinPairExecutionAssignmentSpec.model_validate(
        _dump(assignment)
    )
    assert type(restored.source) is type(source)
    assert _dump(restored) == _dump(assignment)
    assert content_sha256(restored) == content_sha256(assignment)


def test_execute_source_accepts_zero_and_large_exact_integer_seed() -> None:
    assert _execute_source(selection_seed=0).selection_seed == 0
    large = 2**4096 - 1
    assert _execute_source(selection_seed=large).selection_seed == large


@pytest.mark.parametrize(
    ("factory", "field", "bad"),
    [
        (_authoring_ref, "record_id", " "),
        (_authoring_ref, "record_version", "latest"),
        (_domain, "domain_id", ""),
        (_domain, "domain_version", "v1"),
        (_assignment, "assignment_design_id", "\t"),
        (_assignment, "assignment_design_version", "1"),
        (_assignment, "subject_execution_block_id", ""),
        (_assignment, "comparator_execution_block_id", " "),
    ],
)
def test_ids_versions_and_blocks_are_strict(
    factory: object,
    field: str,
    bad: object,
) -> None:
    with pytest.raises(ValidationError):
        if factory is _authoring_ref:
            _authoring_ref("execution_design", **{field: bad})
        else:
            factory(**{field: bad})  # type: ignore[operator]


@pytest.mark.parametrize("bad", [True, "0", -1, 1.5, None, [], {}])
def test_execute_seed_rejects_bool_coercion_and_negative_values(bad: object) -> None:
    with pytest.raises(ValidationError):
        _execute_source(selection_seed=bad)


@pytest.mark.parametrize(
    ("field", "actual", "expected"),
    [
        ("base_execution_design_ref", "pairing_design", "execution_design"),
        ("pairing_ref", "exchangeability_domain", "pairing_design"),
        (
            "exchangeability_domain_ref",
            "execution_design",
            "exchangeability_domain",
        ),
    ],
)
def test_assignment_references_require_exact_local_kinds(
    field: str,
    actual: str,
    expected: str,
) -> None:
    assert actual != expected
    with pytest.raises(ValidationError):
        _assignment(**{field: _authoring_ref(actual)})


def test_assignment_blocks_must_be_distinct() -> None:
    with pytest.raises(ValidationError):
        _assignment(
            subject_execution_block_id="block.same",
            comparator_execution_block_id="block.same",
        )


@pytest.mark.parametrize(
    ("factory", "field_names"),
    [
        (_domain, ("domain_artifact_ref", "canonical_schema_ref")),
        (
            _execute_source,
            (
                "protocol_ref",
                "seed_provenance_ref",
                "seed_provenance_schema_ref",
            ),
        ),
        (
            _import_source,
            (
                "realization_artifact_ref",
                "canonical_schema_ref",
                "generation_protocol_ref",
                "randomization_provenance_ref",
                "randomization_provenance_schema_ref",
            ),
        ),
    ],
)
def test_artifact_roles_require_distinct_content_digests(
    factory: object,
    field_names: tuple[str, ...],
) -> None:
    repeated = _artifact("reused-role-content")
    for left, right in zip(field_names, field_names[1:]):
        with pytest.raises(ValidationError):
            factory(**{left: repeated, right: repeated})  # type: ignore[operator]

    same_digest_different_metadata = ArtifactRef(
        sha256=repeated.sha256,
        media_type="application/octet-stream",
        size_bytes=repeated.size_bytes + 99,
    )
    with pytest.raises(ValidationError):
        factory(  # type: ignore[operator]
            **{
                field_names[0]: repeated,
                field_names[1]: same_digest_different_metadata,
            }
        )


def test_exchangeability_domain_validator_is_a_distinct_content_pin() -> None:
    domain_artifact = _artifact("domain-validator-reuse")
    reused_validator = ImplementationRef(
        implementation_id="implementation.domain-validator",
        version="1.0.0",
        content_sha256=domain_artifact.sha256,
    )
    with pytest.raises(ValidationError):
        _domain(
            domain_artifact_ref=domain_artifact,
            validator=reused_validator,
        )


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_domain, "domain_artifact_ref"),
        (_domain, "canonical_schema_ref"),
        (_execute_source, "protocol_ref"),
        (_execute_source, "seed_provenance_ref"),
        (_execute_source, "seed_provenance_schema_ref"),
        (_import_source, "realization_artifact_ref"),
        (_import_source, "canonical_schema_ref"),
        (_import_source, "generation_protocol_ref"),
        (_import_source, "randomization_provenance_ref"),
        (_import_source, "randomization_provenance_schema_ref"),
    ],
)
def test_nested_artifacts_are_exact_dump_revalidated(
    factory: object,
    field: str,
) -> None:
    class LooseArtifact(ArtifactRef):
        sha256: str

    loose = LooseArtifact(
        sha256="not-a-digest",
        media_type="application/json",
        size_bytes=1,
    )
    with pytest.raises(ValidationError):
        factory(**{field: loose})  # type: ignore[operator]

    unchecked = ArtifactRef.model_construct(
        sha256="unchecked",
        media_type="application/json",
        size_bytes=1,
    )
    with pytest.raises(ValidationError):
        factory(**{field: unchecked})  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (_domain, "validator"),
        (_execute_source, "algorithm"),
        (_execute_source, "seed_provenance_validator"),
        (_import_source, "validator"),
        (_import_source, "randomization_provenance_validator"),
    ],
)
def test_nested_implementation_pins_are_exact_dump_revalidated(
    factory: object,
    field: str,
) -> None:
    class LooseImplementation(ImplementationRef):
        content_sha256: str

    loose = LooseImplementation(
        implementation_id="implementation.loose",
        version="1.0.0",
        content_sha256="bad",
    )
    with pytest.raises(ValidationError):
        factory(**{field: loose})  # type: ignore[operator]

    unchecked = ImplementationRef.model_construct(
        implementation_id="implementation.unchecked",
        version="latest",
        content_sha256="bad",
    )
    with pytest.raises(ValidationError):
        factory(**{field: unchecked})  # type: ignore[operator]


@pytest.mark.parametrize(
    "record",
    [
        _authoring_ref("execution_design"),
        _domain(),
        _execute_source(),
        _import_source(),
        _assignment(),
    ],
)
def test_normally_constructed_concrete_subclasses_are_rejected(record: object) -> None:
    record_type = type(record)

    class Extended(record_type):  # type: ignore[valid-type, misc]
        unauthorized: str = "extra"

    extended = Extended.model_validate(_dump(record))
    with pytest.raises(ValidationError):
        record_type.model_validate(extended)


@pytest.mark.parametrize("source", [_execute_source(), _import_source()])
def test_source_union_rejects_subclass_and_mixed_arm_payloads(source: object) -> None:
    source_type = type(source)

    class Extended(source_type):  # type: ignore[valid-type, misc]
        unauthorized: str = "extra"

    extended = Extended.model_validate(_dump(source))
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionAssignmentSourceSpec).validate_python(extended)

    mixed = dict(_dump(source))  # type: ignore[arg-type]
    if mixed["source_kind"] == "execute_pinned":
        mixed["realization_artifact_ref"] = _dump(_artifact("mixed"))
    else:
        mixed["selection_seed"] = 0
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionAssignmentSourceSpec).validate_python(mixed)


@pytest.mark.parametrize(
    "field",
    [
        "pair_keys",
        "selected_unit_ids",
        "assignment_rows",
        "scope_key",
        "realization_key",
        "plan_cell",
        "run_plan",
        "receipt",
        "p_value",
        "interval",
        "outcome_exclusion_mask",
    ],
)
def test_assignment_rejects_every_later_owned_field(field: str) -> None:
    values = dict(_dump(_assignment()))  # type: ignore[arg-type]
    values[field] = "forbidden"
    with pytest.raises(ValidationError):
        IndependentUniformWithinPairExecutionAssignmentSpec.model_validate(values)


def test_wrong_discriminators_versions_hashes_and_literals_fail_closed() -> None:
    cases = [
        (
            AssignmentAuthoringRecordRef,
            {**_dump(_authoring_ref("execution_design")), "record_type": "other"},
        ),
        (
            AssignmentAuthoringRecordRef,
            {
                **_dump(_authoring_ref("execution_design")),
                "spec_version": "aeread.assignment_authoring_record_ref/9.9",
            },
        ),
        (
            AssignmentAuthoringRecordRef,
            {
                **_dump(_authoring_ref("execution_design")),
                "content_sha256": "A" * 64,
            },
        ),
        (
            ExchangeabilityDomainSpec,
            {**_dump(_domain()), "allocation_unit": "episode"},
        ),
        (
            ExecuteUniformWithinPairAssignmentSourceSpec,
            {**_dump(_execute_source()), "bit_rule": "hash_mod_two"},
        ),
        (
            ImportedUniformWithinPairAssignmentSourceSpec,
            {**_dump(_import_source()), "assignment_law": "predeclared_only"},
        ),
        (
            IndependentUniformWithinPairExecutionAssignmentSpec,
            {**_dump(_assignment()), "pair_coverage_rule": "allow_subset"},
        ),
    ]
    for record_type, values in cases:
        with pytest.raises(ValidationError):
            record_type.model_validate(values)


def test_unchecked_top_level_objects_are_explicitly_untrusted() -> None:
    unchecked = IndependentUniformWithinPairExecutionAssignmentSpec.model_construct(
        assignment_design_id=" ",
        assignment_design_version="latest",
    )
    with pytest.raises(ValidationError):
        IndependentUniformWithinPairExecutionAssignmentSpec.model_validate(
            unchecked.model_dump(mode="python")
        )


def _assignment_source_ast(source: str | None = None) -> ast.Module:
    if source is None:
        source = Path(inspect.getsourcefile(records_module) or "").read_text(
            encoding="utf-8"
        )
    module = ast.parse(source)
    execution_design_indexes = [
        index
        for index, node in enumerate(module.body)
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionDesignSpec"
    ]
    strict_value_indexes = [
        index
        for index, node in enumerate(module.body)
        if isinstance(node, ast.ClassDef) and node.name == "_StrictValueModel"
    ]
    assert len(execution_design_indexes) == 1
    assert len(strict_value_indexes) == 1
    start = execution_design_indexes[0] + 1
    end = strict_value_indexes[0]
    assert start < end
    return ast.Module(body=module.body[start:end], type_ignores=[])


def _assignment_module_scope_bindings(source: str) -> dict[str, list[str]]:
    class ModuleBindingCollector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, list[str]] = {}

        def record(self, name: str, origin: str) -> None:
            self.bindings.setdefault(name, []).append(origin)

        def record_target(self, target: ast.expr, origin: str) -> None:
            if isinstance(target, ast.Name):
                self.record(target.id, origin)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    self.record_target(element, origin)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.record(node.name, "function")
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.record(node.name, "class")
            for expression in (*node.decorator_list, *node.bases):
                self.visit(expression)
            for keyword in node.keywords:
                self.visit(keyword.value)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                self.record(alias.asname or alias.name.split(".")[0], "import")

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            assert all(alias.name != "*" for alias in node.names)
            for alias in node.names:
                self.record(
                    alias.asname or alias.name,
                    f"import-from:{node.module}",
                )

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                self.record_target(target, "assign")
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.record_target(node.target, "assign")
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.record_target(node.target, "assign")
            self.visit(node.value)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.record_target(node.target, "named-expr")
            self.visit(node.value)

        def visit_Delete(self, node: ast.Delete) -> None:
            for target in node.targets:
                self.record_target(target, "delete")

        def visit_For(self, node: ast.For) -> None:
            self.record_target(node.target, "loop")
            self.visit(node.iter)
            for statement in (*node.body, *node.orelse):
                self.visit(statement)

        visit_AsyncFor = visit_For

        def visit_With(self, node: ast.With) -> None:
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    self.record_target(item.optional_vars, "with")
            for statement in node.body:
                self.visit(statement)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name is not None:
                self.record(node.name, "except")
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_comprehension(self, node: ast.comprehension) -> None:
            self.visit(node.iter)
            for condition in node.ifs:
                self.visit(condition)

        def visit_Match(self, node: ast.Match) -> None:
            self.visit(node.subject)
            for case in node.cases:
                for pattern in ast.walk(case.pattern):
                    if isinstance(pattern, (ast.MatchAs, ast.MatchStar)):
                        if pattern.name is not None:
                            self.record(pattern.name, "match")
                    elif isinstance(pattern, ast.MatchMapping):
                        if pattern.rest is not None:
                            self.record(pattern.rest, "match")
                if case.guard is not None:
                    self.visit(case.guard)
                for statement in case.body:
                    self.visit(statement)

        def visit_Global(self, node: ast.Global) -> None:
            for name in node.names:
                self.record(name, "global")

        def visit_TypeAlias(self, node: ast.AST) -> None:
            target = getattr(node, "name")
            if isinstance(target, ast.Name):
                self.record(target.id, "type-alias")
            self.visit(getattr(node, "value"))

    collector = ModuleBindingCollector()
    collector.visit(ast.parse(source))
    return collector.bindings


def _assert_assignment_external_global_bindings(source: str) -> None:
    bindings = _assignment_module_scope_bindings(source)
    expected = {
        "Annotated": ["import-from:typing"],
        "Literal": ["import-from:typing"],
        "Field": ["import-from:pydantic"],
        "model_validator": ["import-from:pydantic"],
        "SDKInt": ["import-from:base"],
        "SDKStr": ["import-from:base"],
        "SHA256": ["assign"],
        "ArtifactRef": ["class"],
        "ImplementationRef": ["class"],
        "_PlannedIdentityRecord": ["class"],
        "_require_non_empty": ["function"],
        "_require_semver": ["function"],
        "_validate_complete_artifact": ["function"],
        "_validate_implementation_pin": ["function"],
        "ValueError": [],
        "len": [],
        "set": [],
        "str": [],
        "tuple": [],
        "type": [],
    }
    assert {name: bindings.get(name, []) for name in expected} == expected
    protected_names = set(expected)
    assert all(
        protected_names.isdisjoint(node.names)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Global)
    )


def _assert_assignment_runtime_global_bindings() -> None:
    assert records_module.Annotated is Annotated
    assert records_module.Literal is Literal
    assert records_module.Field is Field
    assert records_module.model_validator is model_validator
    assert records_module.SDKInt is sdk_base.SDKInt
    assert records_module.SDKStr is sdk_base.SDKStr

    for name in ("ArtifactRef", "ImplementationRef", "_PlannedIdentityRecord"):
        value = getattr(records_module, name)
        assert inspect.isclass(value)
        assert value.__module__ == records_module.__name__
        assert value.__qualname__ == name

    for name in (
        "_require_non_empty",
        "_require_semver",
        "_validate_complete_artifact",
        "_validate_implementation_pin",
    ):
        value = getattr(records_module, name)
        assert inspect.isfunction(value)
        assert value.__module__ == records_module.__name__
        assert value.__qualname__ == name

    for name in ("ValueError", "len", "set", "str", "tuple", "type"):
        assert records_module.__dict__.get(name, getattr(builtins, name)) is getattr(
            builtins, name
        )


def _assert_assignment_top_level_inventory(source: str | None = None) -> ast.Module:
    use_runtime_bindings = source is None
    if source is None:
        source = Path(inspect.getsourcefile(records_module) or "").read_text(
            encoding="utf-8"
        )
    _assert_assignment_external_global_bindings(source)
    if use_runtime_bindings:
        _assert_assignment_runtime_global_bindings()
    module = _assignment_source_ast(source)
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == [
        "AssignmentAuthoringRecordRef",
        "ExchangeabilityDomainSpec",
        "ExecuteUniformWithinPairAssignmentSourceSpec",
        "ImportedUniformWithinPairAssignmentSourceSpec",
        "IndependentUniformWithinPairExecutionAssignmentSpec",
    ]
    assert all(not node.decorator_list for node in classes)
    expected_methods = {
        "AssignmentAuthoringRecordRef": ["validate_assignment_authoring_record_ref"],
        "ExchangeabilityDomainSpec": ["validate_exchangeability_domain"],
        "ExecuteUniformWithinPairAssignmentSourceSpec": [
            "validate_execute_assignment_source"
        ],
        "ImportedUniformWithinPairAssignmentSourceSpec": [
            "validate_imported_assignment_source"
        ],
        "IndependentUniformWithinPairExecutionAssignmentSpec": [
            "validate_execution_assignment"
        ],
    }
    for class_node in classes:
        methods = [
            node for node in class_node.body if isinstance(node, ast.FunctionDef)
        ]
        assert [node.name for node in methods] == expected_methods[class_node.name]
        assert all(
            [ast.unparse(decorator) for decorator in method.decorator_list]
            == ["model_validator(mode='after')"]
            for method in methods
        )
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in functions] == [
        "_validate_assignment_artifact",
        "_validate_assignment_implementation",
        "_validate_distinct_content_sha256",
        "_validate_assignment_record_ref",
    ]
    assert all(not node.decorator_list for node in functions)

    union_assignments = [
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "ExecutionAssignmentSourceSpec"
            for target in node.targets
        )
    ]
    assert len(union_assignments) == 1
    union_surface = ast.unparse(union_assignments[0].value)
    assert union_surface == (
        "Annotated[ExecuteUniformWithinPairAssignmentSourceSpec | "
        "ImportedUniformWithinPairAssignmentSourceSpec, "
        "Field(discriminator='source_kind')]"
    )
    assert len(module.body) == len(classes) + len(functions) + 1
    return module


@pytest.mark.parametrize(
    "shape",
    [
        "paired-fixed-execute",
        "paired-fixed-import",
        "seeded-base-execution-ref",
        "upstream-unseeded-base-execution-ref",
        "judge-free-block-ids",
        "judge-planned-block-ids",
    ],
)
def test_provider_free_pressure_shapes_do_not_change_the_contract(shape: str) -> None:
    source = _import_source() if shape == "paired-fixed-import" else _execute_source()
    assignment = _assignment(
        source=source,
        assignment_design_id=f"assignment.{shape}",
    )
    assert assignment.source.source_kind in {"execute_pinned", "import_predeclared"}
    assert assignment.assignment_mechanism == "independent_uniform_within_pair"


def test_observational_pairing_is_represented_by_absent_overlay() -> None:
    assignment_overlay = None
    assert assignment_overlay is None
    assert not hasattr(sdk_v1, "NoAssignmentSpec")
