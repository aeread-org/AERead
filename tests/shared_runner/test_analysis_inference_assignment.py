"""Task 1.1b4b declaration-only analysis-inference authoring contract."""

from __future__ import annotations

import ast
import builtins
import hashlib
import inspect
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator
import pytest

import aeread.sdk.v1 as sdk_v1
import aeread.sdk.v1.base as sdk_base
import aeread.sdk.v1.records as records_module
from aeread.sdk.v1 import (
    AnalysisSourceRef,
    ClusterBootstrapStabilityIntervalSpec,
    EffectiveResamplingBlockSpec,
    HolmMultiplicityAdjustmentSpec,
    HypothesisTestSpec,
    InferenceCompatibilitySpec,
    IntervalSpec,
    MultiplicityAdjustmentSpec,
    NoHypothesisTestSpec,
    NoIntervalSpec,
    NoMultiplicityAdjustmentSpec,
    PairProjectionSpec,
    PairedRandomizationTestSpec,
    PopulationClusterProjectionSpec,
)


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


def _b4b_source(source: str | None = None) -> str:
    if source is None:
        source = Path(inspect.getsourcefile(records_module) or "").read_text(
            encoding="utf-8"
        )
    module = ast.parse(source)
    rater_summary_indexes = [
        index
        for index, node in enumerate(module.body)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "RaterSummarySpec"
    ]
    starts = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "AnalysisSourceRef"
    ]
    ends = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ValidityDomainSpec"
    ]
    assert len(starts) == len(ends) == 1
    assert len(rater_summary_indexes) == 1
    assert starts[0].lineno < ends[0].lineno
    start_index = module.body.index(starts[0])
    end_index = module.body.index(ends[0])
    assert start_index == rater_summary_indexes[0] + 1
    assert end_index > start_index
    assert isinstance(module.body[end_index - 1], ast.ClassDef)
    assert module.body[end_index - 1].name == "InferenceCompatibilitySpec"
    lines = source.splitlines(keepends=True)
    return "".join(lines[starts[0].lineno - 1 : ends[0].lineno - 1])


def _b4b_module_scope_bindings(source: str) -> dict[str, list[str]]:
    class Collector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, list[str]] = {}

        def record(self, name: str, origin: str) -> None:
            self.bindings.setdefault(name, []).append(origin)

        def target(self, target: ast.expr, origin: str) -> None:
            if isinstance(target, ast.Name):
                self.record(target.id, origin)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for item in target.elts:
                    self.target(item, origin)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.record(node.name, "function")
            for item in (
                *node.decorator_list,
                *node.args.defaults,
                *node.args.kw_defaults,
            ):
                if item is not None:
                    self.visit(item)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.record(node.name, "class")
            for item in (*node.decorator_list, *node.bases):
                self.visit(item)
            for keyword in node.keywords:
                self.visit(keyword.value)

        def visit_Import(self, node: ast.Import) -> None:
            for item in node.names:
                self.record(item.asname or item.name.split(".")[0], "import")

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            assert all(item.name != "*" for item in node.names)
            for item in node.names:
                self.record(item.asname or item.name, f"import-from:{node.module}")

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                self.target(target, "assign")
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.target(node.target, "assign")
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.target(node.target, "augassign")
            self.visit(node.value)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.target(node.target, "namedexpr")
            self.visit(node.value)

        def visit_Delete(self, node: ast.Delete) -> None:
            for target in node.targets:
                self.target(target, "delete")

        def visit_For(self, node: ast.For) -> None:
            self.target(node.target, "for")
            self.generic_visit(node)

        visit_AsyncFor = visit_For

        def visit_With(self, node: ast.With) -> None:
            for item in node.items:
                if item.optional_vars is not None:
                    self.target(item.optional_vars, "with")
            self.generic_visit(node)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name:
                self.record(node.name, "except")
            self.generic_visit(node)

        def visit_Match(self, node: ast.Match) -> None:
            for case in node.cases:
                for item in ast.walk(case.pattern):
                    if isinstance(item, (ast.MatchAs, ast.MatchStar)) and item.name:
                        self.record(item.name, "match")
                    elif isinstance(item, ast.MatchMapping) and item.rest:
                        self.record(item.rest, "match")
            self.generic_visit(node)

        def visit_Global(self, node: ast.Global) -> None:
            for name in node.names:
                self.record(name, "global")

    collector = Collector()
    collector.visit(ast.parse(source))
    return collector.bindings


def _assert_b4b_runtime_bindings() -> None:
    assert records_module.Annotated is Annotated
    assert records_module.Literal is Literal
    assert records_module.Field is Field
    assert records_module.model_validator is model_validator
    assert records_module.SDKInt is sdk_base.SDKInt
    assert records_module.SDKStr is sdk_base.SDKStr
    for name in (
        "_PlannedIdentityRecord",
        "_StrictValueModel",
        "CanonicalRational",
    ):
        value = getattr(records_module, name)
        assert inspect.isclass(value)
        assert value.__module__ == records_module.__name__
        assert value.__qualname__ == name
    for name in (
        "_require_non_empty",
        "_require_semver",
        "_validate_canonical_string_tuple",
    ):
        value = getattr(records_module, name)
        assert inspect.isfunction(value)
        assert value.__module__ == records_module.__name__
        assert value.__qualname__ == name

    def resolve_builtin(function: object, name: str) -> object:
        if name in records_module.__dict__:
            return records_module.__dict__[name]
        value = getattr(function, "__func__", function)
        fallback = getattr(value, "__builtins__")
        return fallback[name] if isinstance(fallback, dict) else getattr(fallback, name)

    functions = [
        getattr(records_module, "_validate_analysis_source_ref"),
        getattr(records_module, "_require_non_empty"),
        getattr(records_module, "_require_semver"),
        PopulationClusterProjectionSpec.validate_population_cluster_projection,
        PairProjectionSpec.validate_pair_projection,
        InferenceCompatibilitySpec.validate_inference_compatibility,
    ]
    for function in functions:
        for name in ("ValueError", "len", "set", "tuple", "type"):
            assert resolve_builtin(function, name) is getattr(builtins, name)


def _assert_b4b_declaration_only(source: str) -> None:
    full_module = ast.parse(source)
    bindings = _b4b_module_scope_bindings(source)
    expected_external = {
        "Annotated": ["import-from:typing"],
        "Literal": ["import-from:typing"],
        "Field": ["import-from:pydantic"],
        "model_validator": ["import-from:pydantic"],
        "SDKInt": ["import-from:base"],
        "SDKStr": ["import-from:base"],
        "SHA256": ["assign"],
        "_PlannedIdentityRecord": ["class"],
        "_StrictValueModel": ["class"],
        "CanonicalRational": ["class"],
        "_require_non_empty": ["function"],
        "_require_semver": ["function"],
        "_validate_canonical_string_tuple": ["function"],
        "__builtins__": [],
        "ValueError": [],
        "len": [],
        "set": [],
        "tuple": [],
        "type": [],
    }
    assert {
        name: bindings.get(name, []) for name in expected_external
    } == expected_external
    assert all(
        not node.decorator_list
        for node in full_module.body
        if isinstance(node, ast.ClassDef) and node.name == "AnalysisSourceRef"
    )
    span = ast.parse(_b4b_source(source))
    class_names = [node.name for node in span.body if isinstance(node, ast.ClassDef)]
    expected_classes = [
        "AnalysisSourceRef",
        "EffectiveResamplingBlockSpec",
        "PopulationClusterProjectionSpec",
        "PairProjectionSpec",
        "NoIntervalSpec",
        "ClusterBootstrapStabilityIntervalSpec",
        "NoHypothesisTestSpec",
        "PairedRandomizationTestSpec",
        "NoMultiplicityAdjustmentSpec",
        "HolmMultiplicityAdjustmentSpec",
        "InferenceCompatibilitySpec",
    ]
    assert class_names == expected_classes
    expected_aliases = [
        "IntervalSpec",
        "HypothesisTestSpec",
        "MultiplicityAdjustmentSpec",
    ]
    aliases = [
        node.targets[0].id
        for node in span.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    assert aliases == expected_aliases
    functions = [node.name for node in span.body if isinstance(node, ast.FunctionDef)]
    assert functions == ["_validate_analysis_source_ref"]
    assert len(span.body) == len(expected_classes) + len(expected_aliases) + 1
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(span)
    )
    assert all(
        not node.decorator_list for node in span.body if isinstance(node, ast.ClassDef)
    )
    expected_methods = {
        "AnalysisSourceRef": ["validate_analysis_source_ref"],
        "EffectiveResamplingBlockSpec": ["validate_effective_resampling_block"],
        "PopulationClusterProjectionSpec": ["validate_population_cluster_projection"],
        "PairProjectionSpec": ["validate_pair_projection"],
        "NoIntervalSpec": [],
        "ClusterBootstrapStabilityIntervalSpec": [
            "validate_cluster_bootstrap_stability_interval"
        ],
        "NoHypothesisTestSpec": [],
        "PairedRandomizationTestSpec": ["validate_paired_randomization_test"],
        "NoMultiplicityAdjustmentSpec": [],
        "HolmMultiplicityAdjustmentSpec": ["validate_holm_multiplicity_adjustment"],
        "InferenceCompatibilitySpec": ["validate_inference_compatibility"],
    }
    for node in span.body:
        if isinstance(node, ast.ClassDef):
            methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
            assert [method.name for method in methods] == expected_methods[node.name]
            assert all(
                [ast.unparse(item) for item in method.decorator_list]
                == ["model_validator(mode='after')"]
                for method in methods
            )
    expected_unions = {
        "IntervalSpec": (
            "Annotated[NoIntervalSpec | ClusterBootstrapStabilityIntervalSpec, "
            "Field(discriminator='interval_kind')]"
        ),
        "HypothesisTestSpec": (
            "Annotated[NoHypothesisTestSpec | PairedRandomizationTestSpec, "
            "Field(discriminator='test_kind')]"
        ),
        "MultiplicityAdjustmentSpec": (
            "Annotated[NoMultiplicityAdjustmentSpec | HolmMultiplicityAdjustmentSpec, "
            "Field(discriminator='multiplicity_kind')]"
        ),
    }
    for node in span.body:
        if isinstance(node, ast.Assign):
            assert ast.unparse(node.value) == expected_unions[node.targets[0].id]
    forbidden = {
        "runtime",
        "resolver",
        "store",
        "registry",
        "artifact",
        "result",
        "receipt",
        "PlanCell",
        "RunPlan",
        "ProviderCall",
        "ResolvedPairedRandomizationBinding",
        "open",
        "Path",
        "random",
        "secrets",
        "__import__",
        "eval",
        "exec",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "importlib",
        "p_value",
    }
    names = {node.id for node in ast.walk(span) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(span) if isinstance(node, ast.Attribute)}
    assert not forbidden & (names | attrs)
    allowed_calls = {
        "AnalysisSourceRef",
        "CanonicalRational",
        "ValueError",
        "Field",
        "model_validator",
        "_require_non_empty",
        "_require_semver",
        "_validate_analysis_source_ref",
        "_validate_canonical_string_tuple",
        "len",
        "set",
        "tuple",
        "type",
        "model_dump",
        "model_validate",
    }
    calls = {
        (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr if isinstance(node.func, ast.Attribute) else "<dynamic>"
        )
        for node in ast.walk(span)
        if isinstance(node, ast.Call)
    }
    assert calls <= allowed_calls
    protected = (
        set(expected_classes)
        | set(expected_aliases)
        | {"_validate_analysis_source_ref"}
    )
    bindings: dict[str, list[str]] = {}
    for node in full_module.body:
        if isinstance(node, ast.ClassDef):
            bindings.setdefault(node.name, []).append("class")
        elif isinstance(node, ast.FunctionDef):
            bindings.setdefault(node.name, []).append("function")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append("assign")
    assert {name: bindings.get(name) for name in protected} == {
        **{name: ["class"] for name in expected_classes},
        **{name: ["assign"] for name in expected_aliases},
        "_validate_analysis_source_ref": ["function"],
    }
    assert not any(
        (protected | set(expected_external)) & set(node.names)
        for node in ast.walk(full_module)
        if isinstance(node, ast.Global)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda source: source.replace(
            "class AnalysisSourceRef",
            '__builtins__["len"] = runtime.provider_hook\n\nclass AnalysisSourceRef',
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            'builtins.__dict__["len"] = runtime.provider_hook\n\nclass AnalysisSourceRef',
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            'vars(__builtins__)["len"] = runtime.provider_hook\n\nclass AnalysisSourceRef',
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            'x = __builtins__\nx["len"] = runtime.provider_hook\n\nclass AnalysisSourceRef',
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "__builtins__ = runtime.builtins\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "model_validator = runtime.provider_hook\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "_require_non_empty = runtime.step\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "(_require_non_empty := runtime.step)\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "match None:\n    case model_validator:\n        pass\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "del _require_non_empty\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "Field = runtime.provider_hook\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "_PlannedIdentityRecord = runtime.base\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef",
            "class Attack:\n    global model_validator\n    model_validator = runtime.provider_hook\n\nclass AnalysisSourceRef",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n",
            "@runtime.decorator\nclass AnalysisSourceRef(_PlannedIdentityRecord):\n",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n",
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n    from runtime import hook\n",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n",
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n    runtime.call()\n",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n",
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n    _local = runtime.value\n",
            1,
        ),
        lambda source: source.replace(
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n",
            "class AnalysisSourceRef(_PlannedIdentityRecord):\n    hidden: PlanCell\n",
            1,
        ),
        lambda source: source.replace(
            "class ValidityDomainSpec",
            "class AnalysisSourceRef:\n    pass\n\nclass ValidityDomainSpec",
            1,
        ),
    ],
)
def test_b4b_source_guard_mutations_must_fail(mutation: object) -> None:
    source = Path(inspect.getsourcefile(records_module) or "").read_text(
        encoding="utf-8"
    )
    with pytest.raises(AssertionError):
        _assert_b4b_declaration_only(mutation(source))  # type: ignore[operator]


def test_b4b_source_guard_locks_external_bindings_and_runtime_identity() -> None:
    source = Path(inspect.getsourcefile(records_module) or "").read_text(
        encoding="utf-8"
    )
    _assert_b4b_declaration_only(source)
    _assert_b4b_runtime_bindings()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _source(kind: str) -> dict[str, object]:
    return {
        "spec_version": "aeread.analysis_source_ref/0.1",
        "record_type": "analysis_source_ref",
        "source_kind": kind,
        "record_id": f"source.{kind}",
        "record_version": "1.0.0",
        "content_sha256": _sha(kind),
    }


def _cluster_projection(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.cluster_projection/0.1",
        "record_type": "cluster_projection",
        "projection_id": "cluster.population",
        "projection_version": "1.0.0",
        "cluster_design_ref": _source("cluster_design"),
        "population_key_field": "population_unit_id",
        "replicate_nesting_rule": "all_plan_cells_for_unit_share_population_cluster",
        "coverage_rule": "exactly_one_population_cluster_per_planned_cell",
        "effective_block_kind": "strict_coarsening",
        "effective_blocks": [
            {
                "effective_block_id": "block.a",
                "population_cluster_ids": ["cluster.a", "cluster.b"],
            }
        ],
        "group_integrity_rule": "pair_and_pass_all_k_groups_wholly_nested",
        "ordering_rule": "effective_block_id_then_canonical_row_identity",
    }
    value.update(overrides)
    return value


def _pair_projection(kind: str = "paired", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.pair_projection/0.1",
        "record_type": "pair_projection",
        "projection_id": "pair.policy",
        "projection_version": "1.0.0",
        "pairing_ref": _source("pairing_design"),
        "pairing_kind": kind,
        "coordinate_source": "resolved_plan_cell_coordinates",
        "direction": "subject_minus_comparator",
        "formation_rule": (
            "one_to_one_equal_pair_keys"
            if kind == "paired"
            else "independent_subject_and_comparator_arms"
        ),
        "duplicate_rule": "reject",
        "missing_pair_rule": "typed_missing_not_drop",
        "ordering_rule": (
            "pair_key_then_subject_then_comparator"
            if kind == "paired"
            else "subject_then_comparator_canonical_row_identity"
        ),
        "projection_scope": "analysis_relation_only",
    }
    value.update(overrides)
    return value


def _no_interval(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.interval/0.1",
        "record_type": "interval",
        "interval_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _stability_interval(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.interval/0.1",
        "record_type": "interval",
        "interval_kind": "cluster_bootstrap_stability",
        "interval_id": "interval.stability",
        "interval_version": "1.0.0",
        "method": "percentile_cluster_bootstrap_stability",
        "coverage_claim": "none_descriptive_only",
        "target": "conditional_on_observed_effective_blocks",
        "central_mass": {"numerator": 9, "denominator": 10},
        "endpoint_definition": "equal_tailed_percentile_endpoints",
        "resample_count": 100,
        "resampling_seed": 0,
        "resampling_unit": "whole_effective_row_block",
        "effective_block_source": "population_cluster_projection",
        "group_integrity_rule": "pair_and_pass_all_k_groups_wholly_nested",
        "estimator_recompute_rule": (
            "complete_declared_estimator_over_all_rows_with_block_multiplicity"
        ),
        "sampler_policy": "aeread.sha256_rejection_uint256_mod_c/0.1",
        "endpoint_quantile_policy": "r7_linear_exact_rational",
        "minimum_effective_blocks": 2,
        "claim_boundary": "no_finite_population_or_superpopulation_coverage_claim",
    }
    value.update(overrides)
    return value


def _no_test(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.hypothesis_test/0.1",
        "record_type": "hypothesis_test",
        "test_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _paired_test(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.hypothesis_test/0.1",
        "record_type": "hypothesis_test",
        "test_kind": "paired_randomization",
        "test_id": "test.paired",
        "test_version": "1.0.0",
        "method": "paired_sign_flip_randomization",
        "execution_assignment_design_ref": _source("execution_assignment_design"),
        "subject_role": "subject",
        "comparator_role": "comparator",
        "role_binding_rule": (
            "match_referenced_design_subject_and_comparator_execution_blocks"
        ),
        "statistic": "absolute_mean_subject_minus_comparator",
        "alternative": "two_sided",
        "extreme_tie_rule": "greater_than_or_equal",
        "pair_eligibility_rule": "every_preregistered_pair_has_exactly_two_valid_arm_outcomes",
        "missing_pair_rule": (
            "typed_ineligible_no_p_value_no_deletion_replacement_or_reassignment"
        ),
        "exhaustive_assignment_vector_threshold": 2,
        "monte_carlo_resample_count": 1,
        "monte_carlo_seed": 0,
        "exhaustive_order": "mask_ascending_pair_key_order_bit0_negative",
        "monte_carlo_policy": "aeread.paired_randomization_sha256_bit/0.1",
        "monte_carlo_correction": "plus_one_numerator_and_denominator",
        "numeric_policy": "aeread.exact_rational_binary64/0.1",
        "interval_requirement": "none",
    }
    value.update(overrides)
    return value


def _no_multiplicity(reason: str = "not_requested") -> dict[str, object]:
    return {
        "spec_version": "aeread.multiplicity/0.1",
        "record_type": "multiplicity",
        "multiplicity_kind": "none",
        "reason": reason,
        "method": "none",
    }


def _holm(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.multiplicity/0.1",
        "record_type": "multiplicity",
        "multiplicity_kind": "holm_familywise",
        "family_id": "family.confirmatory",
        "family_version": "1.0.0",
        "alpha": {"numerator": 1, "denominator": 20},
        "family_membership_source": "task_1_1b5_immutable_preregistered_test_nodes",
        "minimum_family_size": 2,
        "family_cardinality_rule": "at_least_two_distinct_preregistered_test_nodes",
        "family_ordering_rule": "eligible_raw_p_value_then_test_id_followed_by_ineligible_test_id",
        "method": "holm_step_down_familywise",
        "threshold_rule": "alpha_over_original_preregistered_family_size_minus_eligible_rank_plus_one",
        "stop_rule": "stop_rejecting_after_first_nonrejection",
        "adjusted_p_rule": "running_max_rank_scaled_clipped_one",
        "ineligible_test_rule": "retain_in_preregistered_family_cardinality_no_adjusted_p_no_rejection",
        "numeric_policy": "exact_rational",
    }
    value.update(overrides)
    return value


def _compatibility(target: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "spec_version": "aeread.inference_compatibility/0.1",
        "record_type": "inference_compatibility",
        "compatibility_id": "compatibility.example",
        "compatibility_version": "1.0.0",
        "inference_target": target,
        "panel_basis": "fixed_panel",
        "estimator_analysis_unit": "planned_cell",
        "missingness_kind": "planned_population_invalidate",
        "cluster_projection": None,
        "pair_projection": None,
        "interval": _no_interval(),
        "hypothesis_test": _no_test(),
        "multiplicity": _no_multiplicity(),
        "compatibility_matrix_version": "aeread.inference_compatibility_matrix/0.2",
    }
    value.update(overrides)
    return value


def test_task_1_1b4b_publishes_exact_fourteen_name_additive_surface() -> None:
    surface = tuple(sorted(sdk_v1.__all__))
    assert len(surface) == len(set(surface)) == 220
    assert B4B_EXPORTS <= set(surface)
    prior = tuple(name for name in surface if name not in B4B_EXPORTS)
    assert len(prior) == 206
    assert (
        hashlib.sha256(
            json.dumps(prior, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        == "13b0b9a9403d345979e8eb34213a94ad2fc9c91a395af42c326a83d3b40f917f"
    )


def test_all_concrete_records_admit_one_valid_constructor_shape() -> None:
    assert AnalysisSourceRef.model_validate(_source("cluster_design"))
    assert EffectiveResamplingBlockSpec.model_validate(
        {"effective_block_id": "block.a", "population_cluster_ids": ["a"]}
    )


def test_all_six_compatibility_targets_admit_exact_neighboring_shapes() -> None:
    valid = [
        _compatibility("planned_panel_descriptive"),
        _compatibility(
            "finite_population_probability_sample",
            panel_basis="sampled_srswor",
            interval=_no_interval("finite_population_interval_not_supported_v0"),
        ),
        _compatibility(
            "cluster_bootstrap_descriptive_stability",
            cluster_projection=_cluster_projection(),
            interval=_stability_interval(),
        ),
        _compatibility(
            "paired_observational_effect",
            estimator_analysis_unit="pair",
            pair_projection=_pair_projection(),
            hypothesis_test=_no_test("observational_pairing"),
        ),
        _compatibility(
            "unpaired_observational_difference",
            pair_projection=_pair_projection("unpaired"),
            hypothesis_test=_no_test("unpaired_contrast"),
        ),
        _compatibility(
            "paired_randomized_effect",
            estimator_analysis_unit="pair",
            pair_projection=_pair_projection(),
            interval=_no_interval("paired_randomization_test_has_no_interval"),
            hypothesis_test=_paired_test(),
            multiplicity=_holm(),
        ),
    ]
    assert [
        item.inference_target
        for item in map(InferenceCompatibilitySpec.model_validate, valid)
    ] == [
        "planned_panel_descriptive",
        "finite_population_probability_sample",
        "cluster_bootstrap_descriptive_stability",
        "paired_observational_effect",
        "unpaired_observational_difference",
        "paired_randomized_effect",
    ]


def test_b4b_field_order_is_frozen_for_all_eleven_concrete_records() -> None:
    assert {
        record.__name__: tuple(record.model_fields)
        for record in (
            AnalysisSourceRef,
            EffectiveResamplingBlockSpec,
            PopulationClusterProjectionSpec,
            PairProjectionSpec,
            NoIntervalSpec,
            ClusterBootstrapStabilityIntervalSpec,
            NoHypothesisTestSpec,
            PairedRandomizationTestSpec,
            NoMultiplicityAdjustmentSpec,
            HolmMultiplicityAdjustmentSpec,
            InferenceCompatibilitySpec,
        )
    } == {
        "AnalysisSourceRef": (
            "spec_version",
            "record_type",
            "source_kind",
            "record_id",
            "record_version",
            "content_sha256",
        ),
        "EffectiveResamplingBlockSpec": (
            "effective_block_id",
            "population_cluster_ids",
        ),
        "PopulationClusterProjectionSpec": (
            "spec_version",
            "record_type",
            "projection_id",
            "projection_version",
            "cluster_design_ref",
            "population_key_field",
            "replicate_nesting_rule",
            "coverage_rule",
            "effective_block_kind",
            "effective_blocks",
            "group_integrity_rule",
            "ordering_rule",
        ),
        "PairProjectionSpec": (
            "spec_version",
            "record_type",
            "projection_id",
            "projection_version",
            "pairing_ref",
            "pairing_kind",
            "coordinate_source",
            "direction",
            "formation_rule",
            "duplicate_rule",
            "missing_pair_rule",
            "ordering_rule",
            "projection_scope",
        ),
        "NoIntervalSpec": (
            "spec_version",
            "record_type",
            "interval_kind",
            "reason",
            "method",
        ),
        "ClusterBootstrapStabilityIntervalSpec": (
            "spec_version",
            "record_type",
            "interval_kind",
            "interval_id",
            "interval_version",
            "method",
            "coverage_claim",
            "target",
            "central_mass",
            "endpoint_definition",
            "resample_count",
            "resampling_seed",
            "resampling_unit",
            "effective_block_source",
            "group_integrity_rule",
            "estimator_recompute_rule",
            "sampler_policy",
            "endpoint_quantile_policy",
            "minimum_effective_blocks",
            "claim_boundary",
        ),
        "NoHypothesisTestSpec": (
            "spec_version",
            "record_type",
            "test_kind",
            "reason",
            "method",
        ),
        "PairedRandomizationTestSpec": (
            "spec_version",
            "record_type",
            "test_kind",
            "test_id",
            "test_version",
            "method",
            "execution_assignment_design_ref",
            "subject_role",
            "comparator_role",
            "role_binding_rule",
            "statistic",
            "alternative",
            "extreme_tie_rule",
            "pair_eligibility_rule",
            "missing_pair_rule",
            "exhaustive_assignment_vector_threshold",
            "monte_carlo_resample_count",
            "monte_carlo_seed",
            "exhaustive_order",
            "monte_carlo_policy",
            "monte_carlo_correction",
            "numeric_policy",
            "interval_requirement",
        ),
        "NoMultiplicityAdjustmentSpec": (
            "spec_version",
            "record_type",
            "multiplicity_kind",
            "reason",
            "method",
        ),
        "HolmMultiplicityAdjustmentSpec": (
            "spec_version",
            "record_type",
            "multiplicity_kind",
            "family_id",
            "family_version",
            "alpha",
            "family_membership_source",
            "minimum_family_size",
            "family_cardinality_rule",
            "family_ordering_rule",
            "method",
            "threshold_rule",
            "stop_rule",
            "adjusted_p_rule",
            "ineligible_test_rule",
            "numeric_policy",
        ),
        "InferenceCompatibilitySpec": (
            "spec_version",
            "record_type",
            "compatibility_id",
            "compatibility_version",
            "inference_target",
            "panel_basis",
            "estimator_analysis_unit",
            "missingness_kind",
            "cluster_projection",
            "pair_projection",
            "interval",
            "hypothesis_test",
            "multiplicity",
            "compatibility_matrix_version",
        ),
    }


def test_b4b_schema_and_canonical_fixture_hashes_are_frozen() -> None:
    records = {
        "AnalysisSourceRef": AnalysisSourceRef.model_validate(
            _source("cluster_design")
        ),
        "EffectiveResamplingBlockSpec": EffectiveResamplingBlockSpec.model_validate(
            {"effective_block_id": "block.a", "population_cluster_ids": ["a"]}
        ),
        "PopulationClusterProjectionSpec": PopulationClusterProjectionSpec.model_validate(
            _cluster_projection()
        ),
        "PairProjectionSpec": PairProjectionSpec.model_validate(_pair_projection()),
        "NoIntervalSpec": NoIntervalSpec.model_validate(_no_interval()),
        "ClusterBootstrapStabilityIntervalSpec": ClusterBootstrapStabilityIntervalSpec.model_validate(
            _stability_interval()
        ),
        "NoHypothesisTestSpec": NoHypothesisTestSpec.model_validate(_no_test()),
        "PairedRandomizationTestSpec": PairedRandomizationTestSpec.model_validate(
            _paired_test()
        ),
        "NoMultiplicityAdjustmentSpec": NoMultiplicityAdjustmentSpec.model_validate(
            _no_multiplicity()
        ),
        "HolmMultiplicityAdjustmentSpec": HolmMultiplicityAdjustmentSpec.model_validate(
            _holm()
        ),
        "InferenceCompatibilitySpec": InferenceCompatibilitySpec.model_validate(
            _compatibility("planned_panel_descriptive")
        ),
    }
    fixture_digest = {
        name: hashlib.sha256(
            json.dumps(
                record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        for name, record in records.items()
    }
    schema_digest = {
        name: hashlib.sha256(
            json.dumps(
                type(record).model_json_schema(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        for name, record in records.items()
    }
    assert fixture_digest == {
        "AnalysisSourceRef": "5cd95d826e21b12cd9937adc7729797f2faab51ef4273d4ec95c19fb2a907883",
        "EffectiveResamplingBlockSpec": "e501943ae44afb98c5433c3a5bdc5b527a38b4a0a8cea545ac5cb9a1bc2cd825",
        "PopulationClusterProjectionSpec": "eb969d7382095547b97e9554dfde8b4d113718febbc7ff2e869b3f4565149734",
        "PairProjectionSpec": "689a941280b4699f4010a6281a0635f6f2db77ddb23e950d17a05bb1d55ea1da",
        "NoIntervalSpec": "19d8228ba2a01443edfd7fc83635978f3f29f63dbe055b6fa16b34a475bdc68b",
        "ClusterBootstrapStabilityIntervalSpec": "1a7f2b9eb990ca364d9bcaea83f337bf6d4047057cae342c24f610cdbff31b1c",
        "NoHypothesisTestSpec": "dfb958a0188b8b45bcba3e4db3468f5b36740037f6c7293676a2e4f727f4227c",
        "PairedRandomizationTestSpec": "e05abc2bc73be93492e22347c7e8d954953b4a1db856ef35e38f77bcb0e985fe",
        "NoMultiplicityAdjustmentSpec": "ba66f43ea54203523b309e9b68f125d267d093929f93576be33e813931268c10",
        "HolmMultiplicityAdjustmentSpec": "4e2a208a211762571d440c254e9d0b2af5fc01d42c4b293c52eaeb4ea06fe0e1",
        "InferenceCompatibilitySpec": "7a6e4f586c49cb533dc5a4e7867c485a94b5c470d6cfc049153026b1395e8aa6",
    }
    assert schema_digest == {
        "AnalysisSourceRef": "1161f5d0f607a078b4811581c8998c8287ea6494de895e2d1c357eb9a16ac8d9",
        "EffectiveResamplingBlockSpec": "d93106fff17ad6d23cc9ca092894c7e469da17edd3cd40093259565ae5d07a6e",
        "PopulationClusterProjectionSpec": "fe0781d4d81d1b0f19b89ed64dd0d148f5af1c714571cf1590cfdcc9b1936844",
        "PairProjectionSpec": "fdec65895155f73e245a11e2fba58b8522d7bc5bdb999bba2706688b1ad950a8",
        "NoIntervalSpec": "56ceaf011d0c5d5d83dbdb93e852b56ce6c0c47b254d041f53899e80ed20edbf",
        "ClusterBootstrapStabilityIntervalSpec": "fee83f338093bd01c2d6bc218c111e812a983ff8bc4115911ac8a0a93fac9e27",
        "NoHypothesisTestSpec": "a4c6334ceb4799ef9ae2f8ac3eb6d63ff24b4fa506fe047f35c3eddab7416c0a",
        "PairedRandomizationTestSpec": "c9715d562886e650abe8b4b173999e487287611aef2e6bb1fe59f490c851913e",
        "NoMultiplicityAdjustmentSpec": "695af3ad89b61af8f379d2dffbabede398456ea8869951c5f251b1e0ffc20986",
        "HolmMultiplicityAdjustmentSpec": "412d28e88fe020d7e0c5f90774659d44b3e0e6bba4f86c562a429c4a310be63f",
        "InferenceCompatibilitySpec": "481358a1e9584398e9c498ebdc7e4cb3e76e3bc7c9fb5f3981a665799772b15f",
    }
    assert PopulationClusterProjectionSpec.model_validate(_cluster_projection())
    assert PairProjectionSpec.model_validate(_pair_projection())
    assert NoIntervalSpec.model_validate(_no_interval())
    assert ClusterBootstrapStabilityIntervalSpec.model_validate(_stability_interval())
    assert NoHypothesisTestSpec.model_validate(_no_test())
    assert PairedRandomizationTestSpec.model_validate(_paired_test())
    assert NoMultiplicityAdjustmentSpec.model_validate(_no_multiplicity())
    assert HolmMultiplicityAdjustmentSpec.model_validate(_holm())
    assert InferenceCompatibilitySpec.model_validate(
        _compatibility(
            "planned_panel_descriptive", missingness_kind="complete_case_conditional"
        )
    )


@pytest.mark.parametrize(
    ("factory", "record_type", "overrides"),
    [
        (
            _cluster_projection,
            PopulationClusterProjectionSpec,
            {"cluster_design_ref": _source("pairing_design")},
        ),
        (
            _cluster_projection,
            PopulationClusterProjectionSpec,
            {
                "effective_blocks": [
                    {
                        "effective_block_id": "block.a",
                        "population_cluster_ids": ["b", "a"],
                    }
                ]
            },
        ),
        (
            _pair_projection,
            PairProjectionSpec,
            {"formation_rule": "independent_subject_and_comparator_arms"},
        ),
        (
            _paired_test,
            PairedRandomizationTestSpec,
            {"execution_assignment_design_ref": _source("pairing_design")},
        ),
        (
            _stability_interval,
            ClusterBootstrapStabilityIntervalSpec,
            {"central_mass": {"numerator": 1, "denominator": 1}},
        ),
        (
            _holm,
            HolmMultiplicityAdjustmentSpec,
            {"alpha": {"numerator": 1, "denominator": 1}},
        ),
    ],
)
def test_local_declarations_reject_invalid_intrinsic_contracts(
    factory: object, record_type: object, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        record_type.model_validate(factory(**overrides))  # type: ignore[union-attr,operator]


@pytest.mark.parametrize(
    "overrides", [{"record_id": " "}, {"record_version": "latest"}]
)
def test_analysis_source_ref_requires_pinned_nonblank_identity(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceRef.model_validate({**_source("cluster_design"), **overrides})


@pytest.mark.parametrize(
    "target,overrides",
    [
        (
            "planned_panel_descriptive",
            {"cluster_projection": _cluster_projection()},
        ),
        (
            "finite_population_probability_sample",
            {"panel_basis": "sampled_srswor", "interval": _stability_interval()},
        ),
        (
            "cluster_bootstrap_descriptive_stability",
            {"interval": _no_interval()},
        ),
        (
            "paired_observational_effect",
            {
                "estimator_analysis_unit": "pair",
                "pair_projection": _pair_projection(),
                "hypothesis_test": _paired_test(),
            },
        ),
        (
            "unpaired_observational_difference",
            {
                "pair_projection": _pair_projection("unpaired"),
                "hypothesis_test": _paired_test(),
            },
        ),
        (
            "paired_randomized_effect",
            {
                "estimator_analysis_unit": "pair",
                "pair_projection": _pair_projection(),
                "hypothesis_test": _paired_test(),
                "interval": _no_interval("paired_randomization_test_has_no_interval"),
                "missingness_kind": "complete_case_conditional",
            },
        ),
    ],
)
def test_inference_compatibility_rejects_closed_matrix_mismatches(
    target: str, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        InferenceCompatibilitySpec.model_validate(_compatibility(target, **overrides))


def test_discriminated_unions_normalize_raw_dicts_and_reject_mixed_arms() -> None:
    assert isinstance(
        TypeAdapter(IntervalSpec).validate_python(_no_interval()), NoIntervalSpec
    )
    with pytest.raises(ValidationError):
        TypeAdapter(IntervalSpec).validate_python(
            {**_no_interval(), "interval_id": "unauthorized"}
        )
    assert isinstance(
        TypeAdapter(HypothesisTestSpec).validate_python(_no_test()),
        NoHypothesisTestSpec,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(HypothesisTestSpec).validate_python(
            {**_no_test(), "test_id": "unauthorized"}
        )
    assert isinstance(
        TypeAdapter(MultiplicityAdjustmentSpec).validate_python(_no_multiplicity()),
        NoMultiplicityAdjustmentSpec,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(MultiplicityAdjustmentSpec).validate_python(
            {**_no_multiplicity(), "family_id": "unauthorized"}
        )
