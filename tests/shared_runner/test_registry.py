from __future__ import annotations

import builtins
from decimal import Decimal
from fractions import Fraction
import inspect
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import FunctionType
from typing import Annotated, get_type_hints

import pytest
from annotated_types import Gt
from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError, create_model
from pydantic.fields import FieldInfo
from pydantic.types import Strict
from pydantic_core import PydanticUndefined

from aeread.runner.registry import (
    DuplicateReferenceImplementation,
    DuplicatePluginRegistration,
    IncompatiblePlugin,
    InvalidReferenceImplementation,
    PluginRegistry,
    PluginVersionMismatch,
    ReferenceImplementationHashMismatch,
    ReferenceImplementationRegistry,
    ReferenceImplementationRoleMismatch,
    ReferenceImplementationVersionMismatch,
    RegisteredReferenceImplementation,
    UnknownReferenceImplementation,
    UnknownPlugin,
)
from aeread.sdk.v1 import (
    AgentAdapter,
    AttemptObserver,
    BenchmarkSourceAdapter,
    EnvironmentPlugin,
    ExecutionBackend,
    OfficialVerifierBridge,
    ImplementationRef,
    PluginManifest,
    PluginRef,
    UntrustedPluginReference,
    VerifierPlugin,
)
from .fakes import (
    FakeAgentAdapter,
    FakeAttemptObserver,
    FakeBenchmarkSource,
    FakeEnvironment,
    FakeExecutionBackend,
    FakeVerifier,
    MissingStepEnvironment,
)


EXACT_NUMBER_VALIDATOR_SOURCE_SHA256 = (
    "4ae7c3f529ac45ceeb024f2beee15a082a793adbae6686733085a878dd95a43e"
)


def _one_metadata(
    metadata: list[object] | tuple[object, ...],
    expected_type: type[object],
) -> object:
    matches = [item for item in metadata if type(item) is expected_type]
    assert (
        len(matches) == 1
    ), f"expected one {expected_type.__name__} metadata item: {metadata!r}"
    return matches[0]


def _assert_call_attempt_timeout_type_contract(record_type: type[object]) -> None:
    from aeread.sdk.v1 import base as sdk_base

    exact_number_validator = sdk_base._require_exact_number
    validator_source = inspect.getsource(exact_number_validator).encode()
    assert hashlib.sha256(validator_source).hexdigest() == (
        EXACT_NUMBER_VALIDATOR_SOURCE_SHA256
    )
    assert exact_number_validator.__module__ == "aeread.sdk.v1.base"
    assert exact_number_validator.__qualname__ == "_require_exact_number"
    assert exact_number_validator.__closure__ is None
    function_builtins = exact_number_validator.__builtins__
    for name, builtin in (
        ("type", builtins.type),
        ("int", builtins.int),
        ("float", builtins.float),
    ):
        if name in exact_number_validator.__globals__:
            resolved = exact_number_validator.__globals__[name]
        elif isinstance(function_builtins, dict):
            resolved = function_builtins[name]
        else:
            resolved = getattr(function_builtins, name)
        assert resolved is builtin

    canonical_finite_metadata = [
        item
        for item in Field(strict=True, allow_inf_nan=False).metadata
        if getattr(item, "allow_inf_nan", None) is False
    ]
    assert len(canonical_finite_metadata) == 1
    finite_metadata_type = type(canonical_finite_metadata[0])

    declared_type = get_type_hints(record_type, include_extras=True)["timeout_seconds"]
    assert declared_type.__origin__ is float
    assert len(declared_type.__metadata__) == 2
    declared_validator = _one_metadata(declared_type.__metadata__, BeforeValidator)
    declared_field = _one_metadata(declared_type.__metadata__, FieldInfo)
    assert declared_validator.func is exact_number_validator
    assert (
        getattr(declared_validator, "json_schema_input_type", PydanticUndefined)
        is PydanticUndefined
    )
    assert declared_field.is_required()
    assert declared_field.default is PydanticUndefined
    assert declared_field.annotation is None
    assert len(declared_field.metadata) == 2
    declared_strict = _one_metadata(declared_field.metadata, Strict)
    declared_finite = _one_metadata(declared_field.metadata, finite_metadata_type)
    assert declared_strict.strict is True
    assert declared_finite.allow_inf_nan is False

    field = record_type.model_fields["timeout_seconds"]  # type: ignore[attr-defined]
    assert field.is_required()
    assert field.default is PydanticUndefined
    assert field.annotation is float
    assert len(field.metadata) == 4
    gt = _one_metadata(field.metadata, Gt)
    model_validator = _one_metadata(field.metadata, BeforeValidator)
    strict = _one_metadata(field.metadata, Strict)
    finite = _one_metadata(field.metadata, finite_metadata_type)
    assert gt == Gt(gt=0)
    assert model_validator.func is exact_number_validator
    assert (
        getattr(model_validator, "json_schema_input_type", PydanticUndefined)
        is PydanticUndefined
    )
    assert strict.strict is True
    assert finite.allow_inf_nan is False


def test_registry_resolves_exact_environment_version() -> None:
    environment = FakeEnvironment()
    registry = PluginRegistry.from_objects(environments=[environment])

    assert registry.resolve_environment("fake_market", "1.0.0") is environment


def test_registry_resolves_every_supported_plugin_category() -> None:
    environment = FakeEnvironment()
    source = FakeBenchmarkSource()
    verifier = FakeVerifier()
    agent = FakeAgentAdapter()
    backend = FakeExecutionBackend()
    registry = PluginRegistry.from_objects(
        environments=[environment],
        benchmark_sources=[source],
        verifiers=[verifier],
        agent_adapters=[agent],
        execution_backends=[backend],
    )

    assert registry.resolve_environment("fake_market", "1.0.0") is environment
    assert registry.resolve_benchmark_source("fake_source", "1.0.0") is source
    assert registry.resolve_verifier("fake_verifier", "1.0.0") is verifier
    assert registry.resolve_agent_adapter("fake_agent", "1.0.0") is agent
    assert registry.resolve_execution_backend("fake_backend", "1.0.0") is backend


@pytest.mark.parametrize(
    "plugin_id",
    ("", "os:system", "pkg/module", "white space", "plugin()", ".hidden"),
)
def test_plugin_ref_rejects_untrusted_plugin_ids(plugin_id: str) -> None:
    with pytest.raises(UntrustedPluginReference):
        PluginRef(plugin_id=plugin_id, plugin_version="1.0.0")


@pytest.mark.parametrize("version", ("", "v1", "1", "1.0", "1.0.0.0", "1.0.0 beta"))
def test_plugin_ref_rejects_non_semantic_versions(version: str) -> None:
    with pytest.raises(UntrustedPluginReference):
        PluginRef(plugin_id="aeread.exchange_v1", plugin_version=version)


def test_plugin_ref_accepts_namespaced_id_and_full_semver() -> None:
    ref = PluginRef(
        plugin_id="aeread.exchange_v1-compat",
        plugin_version="2.1.0-rc.1+build.7",
    )

    assert ref.plugin_id == "aeread.exchange_v1-compat"
    assert ref.plugin_version == "2.1.0-rc.1+build.7"


def test_registry_rejects_sdk_mismatch_from_unchecked_manifest_copy() -> None:
    environment = FakeEnvironment()
    incompatible = environment.with_manifest(
        environment.manifest.model_copy(update={"sdk_api": "aeread.sdk/v2"})
    )

    with pytest.raises(IncompatiblePlugin, match="sdk_api"):
        PluginRegistry.from_objects(environments=[incompatible])


@pytest.mark.parametrize(
    ("update", "message"),
    (
        ({"spec_version": "aeread.sdk_record/2"}, "spec_version"),
        ({"undeclared_import": "package.module:plugin"}, "manifest"),
        ({"plugin_id": "package/module"}, "manifest reference"),
        ({"plugin_version": "latest"}, "manifest reference"),
    ),
)
def test_registry_revalidates_all_unchecked_manifest_state(
    update: dict[str, object], message: str
) -> None:
    environment = FakeEnvironment()
    unchecked = environment.with_manifest(
        environment.manifest.model_copy(update=update)
    )

    with pytest.raises(IncompatiblePlugin, match=message):
        PluginRegistry.from_objects(environments=[unchecked])


def test_registry_rejects_duplicate_id_and_version_within_category() -> None:
    environment = FakeEnvironment()

    with pytest.raises(DuplicatePluginRegistration):
        PluginRegistry.from_objects(environments=[environment, environment])


def test_same_id_and_version_are_independent_across_categories() -> None:
    environment = FakeEnvironment()
    verifier = FakeVerifier(
        manifest=PluginManifest(
            plugin_id="fake_market",
            plugin_version="1.0.0",
            sdk_api="aeread.sdk/v1",
        )
    )

    registry = PluginRegistry.from_objects(
        environments=[environment], verifiers=[verifier]
    )

    assert registry.resolve_environment("fake_market", "1.0.0") is environment
    assert registry.resolve_verifier("fake_market", "1.0.0") is verifier


def test_registry_distinguishes_unknown_id_from_wrong_version() -> None:
    registry = PluginRegistry.from_objects(environments=[FakeEnvironment()])

    with pytest.raises(UnknownPlugin):
        registry.resolve_environment("unknown", "1.0.0")
    with pytest.raises(PluginVersionMismatch) as exc_info:
        registry.resolve_environment("fake_market", "2.0.0")

    assert exc_info.value.available_versions == ("1.0.0",)


def test_registry_rejects_missing_or_invalid_manifests() -> None:
    class MissingManifest:
        pass

    class MappingManifest:
        manifest = {
            "plugin_id": "mapping",
            "plugin_version": "1.0.0",
            "sdk_api": "aeread.sdk/v1",
        }

    with pytest.raises(IncompatiblePlugin, match="(?i)manifest"):
        PluginRegistry.from_objects(environments=[MissingManifest()])
    with pytest.raises(IncompatiblePlugin, match="PluginManifest"):
        PluginRegistry.from_objects(environments=[MappingManifest()])


def test_registry_wraps_hostile_manifest_type_inspection() -> None:
    class HostileManifest:
        @property
        def __class__(self) -> type[object]:
            raise RuntimeError("manifest class exploded")

    class HostileEnvironment:
        manifest = HostileManifest()

    with pytest.raises(IncompatiblePlugin, match="environments") as exc_info:
        PluginRegistry.from_objects(environments=[HostileEnvironment()])

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_registry_rejects_object_that_does_not_implement_its_category() -> None:
    with pytest.raises(IncompatiblePlugin, match="EnvironmentPlugin"):
        PluginRegistry.from_objects(environments=[MissingStepEnvironment()])


def test_registry_rejects_environment_with_incompatible_step_signature() -> None:
    class BadEnvironment(FakeEnvironment):
        def step(self, case: object) -> object:
            return case

    with pytest.raises(IncompatiblePlugin, match="step"):
        PluginRegistry.from_objects(environments=[BadEnvironment()])


def test_registry_accepts_variadic_environment_call_shape() -> None:
    class VariadicEnvironment(FakeEnvironment):
        def step(self, *args: object, **kwargs: object) -> object:
            return {}

    environment = VariadicEnvironment()
    registry = PluginRegistry.from_objects(environments=[environment])

    assert registry.resolve_environment("fake_market", "1.0.0") is environment


def test_registry_accepts_positional_only_environment_call_shape() -> None:
    class PositionalOnlyEnvironment(FakeEnvironment):
        def legal(self, a: object, b: object, c: object, d: object, /) -> object:
            return {}

    environment = PositionalOnlyEnvironment()
    registry = PluginRegistry.from_objects(environments=[environment])

    assert registry.resolve_environment("fake_market", "1.0.0") is environment


def test_registry_accepts_optional_trailing_plugin_parameter() -> None:
    class OptionalSource(FakeBenchmarkSource):
        def enumerate_cases(
            self, split: str, optional_filter: object = None
        ) -> tuple[()]:
            return ()

    source = OptionalSource()
    registry = PluginRegistry.from_objects(benchmark_sources=[source])

    assert registry.resolve_benchmark_source("fake_source", "1.0.0") is source


def test_registry_rejects_reordered_environment_arguments() -> None:
    class ReorderedEnvironment(FakeEnvironment):
        def legal(
            self,
            state: object,
            case: object,
            phase: object,
            bundle: object,
        ) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="legal"):
        PluginRegistry.from_objects(environments=[ReorderedEnvironment()])


def test_registry_rejects_uninspectable_environment_callable() -> None:
    class UninspectableCallable:
        @property
        def __signature__(self) -> object:
            raise ValueError("opaque callable")

        def __call__(self, *args: object, **kwargs: object) -> object:
            return {}

    class BadEnvironment(FakeEnvironment):
        step = UninspectableCallable()

    with pytest.raises(IncompatiblePlugin, match="step"):
        PluginRegistry.from_objects(environments=[BadEnvironment()])


def test_registry_wraps_plugin_controlled_signature_failure() -> None:
    class RaisingSignatureCallable:
        @property
        def __signature__(self) -> object:
            raise RuntimeError("signature exploded")

        def __call__(self, *args: object, **kwargs: object) -> object:
            return {}

    class BadEnvironment(FakeEnvironment):
        step = RaisingSignatureCallable()

    with pytest.raises(IncompatiblePlugin, match="step") as exc_info:
        PluginRegistry.from_objects(environments=[BadEnvironment()])

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_registry_rejects_async_deterministic_verifier() -> None:
    class BadVerifier(FakeVerifier):
        async def score(
            self, case: object, outcome: object, evidence: object
        ) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="score"):
        PluginRegistry.from_objects(verifiers=[BadVerifier()])


def test_registry_rejects_source_with_unsatisfied_required_parameter() -> None:
    class BadSource(FakeBenchmarkSource):
        def enumerate_cases(self, split: str, required_extra: object) -> tuple[()]:
            return ()

    with pytest.raises(IncompatiblePlugin, match="enumerate_cases"):
        PluginRegistry.from_objects(benchmark_sources=[BadSource()])


def test_registry_rejects_sync_agent_act() -> None:
    class SyncAgent(FakeAgentAdapter):
        def act(self, request: object, *, attempts: object) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="act"):
        PluginRegistry.from_objects(agent_adapters=[SyncAgent()])


def test_registry_requires_agent_attempts_to_be_keyword_only() -> None:
    class PositionalAttemptsAgent(FakeAgentAdapter):
        async def act(self, request: object, attempts: object) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="attempts"):
        PluginRegistry.from_objects(agent_adapters=[PositionalAttemptsAgent()])


def test_registry_accepts_variadic_agent_with_keyword_only_attempts() -> None:
    class VariadicAgent(FakeAgentAdapter):
        async def act(
            self, *args: object, attempts: object, **kwargs: object
        ) -> object:
            return {}

    agent = VariadicAgent()
    registry = PluginRegistry.from_objects(agent_adapters=[agent])

    assert registry.resolve_agent_adapter("fake_agent", "1.0.0") is agent


def test_registry_rejects_unknown_agent_call_observability() -> None:
    class BadObservabilityAgent(FakeAgentAdapter):
        call_observability = "provider_maybe"

    with pytest.raises(IncompatiblePlugin, match="call_observability"):
        PluginRegistry.from_objects(
            agent_adapters=[BadObservabilityAgent(call_observability="provider_maybe")]
        )


def test_registry_wraps_unhashable_agent_call_observability() -> None:
    agent = FakeAgentAdapter(call_observability=[])

    with pytest.raises(IncompatiblePlugin, match="call_observability"):
        PluginRegistry.from_objects(agent_adapters=[agent])


def test_registry_wraps_raising_agent_call_observability_property() -> None:
    class RaisingObservabilityAgent:
        manifest = FakeAgentAdapter().manifest

        @property
        def call_observability(self) -> str:
            raise RuntimeError("observability exploded")

        async def act(self, request: object, *, attempts: object) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="agent_adapters") as exc_info:
        PluginRegistry.from_objects(agent_adapters=[RaisingObservabilityAgent()])

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_registry_wraps_raising_manifest_property() -> None:
    class RaisingManifestEnvironment:
        @property
        def manifest(self) -> object:
            raise RuntimeError("manifest exploded")

    with pytest.raises(IncompatiblePlugin, match="environments") as exc_info:
        PluginRegistry.from_objects(environments=[RaisingManifestEnvironment()])

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_registry_rejects_sync_execution_backend_method() -> None:
    class BadBackend(FakeExecutionBackend):
        def run(self, handle: object, request: object) -> object:
            return object()

    with pytest.raises(IncompatiblePlugin, match="run"):
        PluginRegistry.from_objects(execution_backends=[BadBackend()])


def test_entry_point_discovery_queries_only_the_five_allowlisted_groups() -> None:
    plugins = {
        "aeread.environments": FakeEnvironment(),
        "aeread.benchmark_sources": FakeBenchmarkSource(),
        "aeread.verifiers": FakeVerifier(),
        "aeread.agent_adapters": FakeAgentAdapter(),
        "aeread.execution_backends": FakeExecutionBackend(),
    }
    queried: list[str] = []
    loaded: list[str] = []

    class FakeEntryPoint:
        def __init__(self, group: str) -> None:
            self.group = group

        def load(self) -> object:
            loaded.append(self.group)
            return plugins[self.group]

    def entry_points(*, group: str) -> tuple[FakeEntryPoint, ...]:
        queried.append(group)
        return (FakeEntryPoint(group),)

    registry = PluginRegistry.discover(entry_points_provider=entry_points)

    assert queried == list(plugins)
    assert loaded == list(plugins)
    assert (
        registry.resolve_environment("fake_market", "1.0.0")
        is plugins["aeread.environments"]
    )


def test_discovery_wraps_raising_entry_point_load_attribute_safely() -> None:
    class HostileEntryPoint:
        @property
        def name(self) -> str:
            raise RuntimeError("name exploded")

        @property
        def load(self) -> object:
            raise RuntimeError("load attribute exploded")

        def __repr__(self) -> str:
            raise RuntimeError("repr exploded")

    def entry_points(*, group: str) -> tuple[HostileEntryPoint, ...]:
        return (HostileEntryPoint(),) if group == "aeread.environments" else ()

    with pytest.raises(IncompatiblePlugin) as exc_info:
        PluginRegistry.discover(entry_points_provider=entry_points)

    message = str(exc_info.value)
    assert "environments" in message
    assert "aeread.environments" in message
    assert "index=0" in message
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_discovery_wraps_entry_point_load_call_failure_with_safe_name() -> None:
    class BrokenEntryPoint:
        name = "broken-loader"

        def load(self) -> object:
            raise OSError("distribution import failed")

    def entry_points(*, group: str) -> tuple[BrokenEntryPoint, ...]:
        return (BrokenEntryPoint(),) if group == "aeread.environments" else ()

    with pytest.raises(IncompatiblePlugin) as exc_info:
        PluginRegistry.discover(entry_points_provider=entry_points)

    message = str(exc_info.value)
    assert "environments" in message
    assert "aeread.environments" in message
    assert "broken-loader" in message
    assert isinstance(exc_info.value.__cause__, OSError)


def test_protocols_are_runtime_checkable_and_missing_methods_are_rejected() -> None:
    assert isinstance(FakeEnvironment(), EnvironmentPlugin)
    assert isinstance(FakeVerifier(), VerifierPlugin)
    assert isinstance(FakeAgentAdapter(), AgentAdapter)
    assert isinstance(FakeAttemptObserver(), AttemptObserver)
    assert isinstance(FakeExecutionBackend(), ExecutionBackend)
    assert isinstance(FakeBenchmarkSource(), BenchmarkSourceAdapter)
    assert not isinstance(MissingStepEnvironment(), EnvironmentPlugin)


def test_protocol_method_boundaries_resolve_and_preserve_call_direction() -> None:
    initial_state_hints = get_type_hints(EnvironmentPlugin.initial_state)
    environment_hints = get_type_hints(EnvironmentPlugin.parse_action)
    verifier_hints = get_type_hints(VerifierPlugin.score)
    adapter_hints = get_type_hints(AgentAdapter.act)
    observer_start_hints = get_type_hints(AttemptObserver.call_started)
    observer_success_hints = get_type_hints(AttemptObserver.call_succeeded)
    observer_failure_hints = get_type_hints(AttemptObserver.call_failed)
    bridge_hints = get_type_hints(OfficialVerifierBridge.evaluate_aeread)

    from aeread.sdk.v1 import (
        AttemptObserver as AttemptObserverType,
        AgentRequest,
        CallAttemptStart,
        CallAttemptToken,
        CanonicalResponse,
        ProviderCallFailure,
        ProviderCallResult,
        ScoreEnvelope,
        SealedEvidenceView,
    )

    assert initial_state_hints["cell"].__name__ == "PlanCellT"
    assert environment_hints["response"] is CanonicalResponse
    assert verifier_hints["evidence"] is SealedEvidenceView
    assert adapter_hints["request"] is AgentRequest
    assert adapter_hints["attempts"] is AttemptObserverType
    assert adapter_hints["return"] is CanonicalResponse
    assert observer_start_hints == {
        "start": CallAttemptStart,
        "return": CallAttemptToken,
    }
    assert observer_success_hints == {
        "token": CallAttemptToken,
        "result": ProviderCallResult,
        "return": type(None),
    }
    assert observer_failure_hints == {
        "token": CallAttemptToken,
        "failure": ProviderCallFailure,
        "return": type(None),
    }
    assert bridge_hints["return"] is ScoreEnvelope
    assert inspect.iscoroutinefunction(AgentAdapter.act)
    assert {
        name
        for name, value in vars(AgentAdapter).items()
        if not name.startswith("_") and callable(value)
    } == {"act"}
    assert {
        name
        for name, value in vars(AttemptObserver).items()
        if not name.startswith("_") and callable(value)
    } == {"call_started", "call_succeeded", "call_failed"}

    expected_parameters = {
        AttemptObserver.call_started: ("self", "start"),
        AttemptObserver.call_succeeded: ("self", "token", "result"),
        AttemptObserver.call_failed: ("self", "token", "failure"),
    }
    for method, expected_names in expected_parameters.items():
        parameters = tuple(inspect.signature(method).parameters.values())
        assert tuple(parameter.name for parameter in parameters) == expected_names
        assert all(
            parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            and parameter.default is inspect.Parameter.empty
            for parameter in parameters
        )

    adapter_parameters = tuple(inspect.signature(AgentAdapter.act).parameters.values())
    assert tuple(parameter.name for parameter in adapter_parameters) == (
        "self",
        "request",
        "attempts",
    )
    assert tuple(parameter.kind for parameter in adapter_parameters) == (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in adapter_parameters
    )


def test_legacy_call_attempt_record_schemas_and_validation_remain_stable() -> None:
    from aeread.sdk.v1 import CallAttemptStart, CallAttemptToken

    expected_schema_digests = {
        CallAttemptStart: (
            "4eca45f3315b76e5bf48b5b83cdb922d0d143f794bb18f80aee1ccbe8a6c9ad5"
        ),
        CallAttemptToken: (
            "60c8af077325bdf1a1c7c650f1de619f4e2b7a60d434acd2f4042628ea55e0e8"
        ),
    }
    for record_type, expected_digest in expected_schema_digests.items():
        schema_bytes = json.dumps(
            record_type.model_json_schema(), sort_keys=True, separators=(",", ":")
        ).encode()
        assert hashlib.sha256(schema_bytes).hexdigest() == expected_digest

    valid_start = {
        "call_attempt_id": "call-1",
        "logical_action_id": "logical-1",
        "ordinal": 1,
        "request_sha256": "request-sha",
        "provider": "provider",
        "model": "model",
        "timeout_seconds": 1.0,
        "output_token_limit": 1,
    }
    start = CallAttemptStart(**valid_start)
    assert start.model_fields_set == {
        "call_attempt_id",
        "logical_action_id",
        "ordinal",
        "request_sha256",
        "provider",
        "model",
        "timeout_seconds",
        "output_token_limit",
    }
    assert CallAttemptToken(call_attempt_id="call-1").call_attempt_id == "call-1"
    assert start.retry_reason is None
    assert start.input_token_limit is None
    assert start.spec_version == "aeread.sdk_record/1"
    populated_optionals = CallAttemptStart(
        **(
            valid_start
            | {
                "retry_reason": "transport",
                "input_token_limit": 1,
                "timeout_seconds": 1,
            }
        )
    )
    assert populated_optionals.retry_reason == "transport"
    assert populated_optionals.input_token_limit == 1
    assert populated_optionals.timeout_seconds == 1.0

    required_fields = tuple(valid_start)
    for field_name in required_fields:
        with pytest.raises(ValidationError):
            CallAttemptStart(
                **{key: value for key, value in valid_start.items() if key != field_name}
            )

    for field_name in (
        "call_attempt_id",
        "logical_action_id",
        "retry_reason",
        "request_sha256",
        "provider",
        "model",
    ):
        for invalid in (b"coercion", 1):
            with pytest.raises(ValidationError):
                CallAttemptStart(**(valid_start | {field_name: invalid}))

    for field_name in ("ordinal", "input_token_limit", "output_token_limit"):
        for invalid in ("1", True):
            with pytest.raises(ValidationError):
                CallAttemptStart(**(valid_start | {field_name: invalid}))

    for invalid in (
        "1.0",
        True,
        Decimal("1.0"),
        Fraction(1, 2),
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        with pytest.raises(ValidationError):
            CallAttemptStart(**(valid_start | {"timeout_seconds": invalid}))

    for field_name in ("ordinal", "input_token_limit", "output_token_limit"):
        with pytest.raises(ValidationError):
            CallAttemptStart(**(valid_start | {field_name: 0}))
    with pytest.raises(ValidationError):
        CallAttemptStart(**(valid_start | {"timeout_seconds": 0.0}))
    with pytest.raises(ValidationError):
        CallAttemptStart(**(valid_start | {"spec_version": "aeread.sdk_record/2"}))
    with pytest.raises(ValidationError):
        CallAttemptStart(**(valid_start | {"unexpected": "drift"}))
    with pytest.raises(ValidationError):
        setattr(start, "ordinal", 2)

    with pytest.raises(ValidationError):
        CallAttemptToken()
    for invalid in (b"call-1", 1):
        with pytest.raises(ValidationError):
            CallAttemptToken(call_attempt_id=invalid)
    with pytest.raises(ValidationError):
        CallAttemptToken(
            call_attempt_id="call-1", spec_version="aeread.sdk_record/2"
        )
    with pytest.raises(ValidationError):
        CallAttemptToken(call_attempt_id="call-1", unexpected="drift")
    token = CallAttemptToken(call_attempt_id="call-1")
    with pytest.raises(ValidationError):
        setattr(token, "call_attempt_id", "call-2")


def test_call_attempt_timeout_has_explicit_raw_input_probes() -> None:
    from aeread.sdk.v1 import CallAttemptStart

    class IntSubclass(int):
        pass

    class FloatSubclass(float):
        pass

    class FloatProtocol:
        def __float__(self) -> float:
            return 1.0

    class IndexProtocol:
        def __index__(self) -> int:
            return 1

    class PathLikeProtocol(os.PathLike[str]):
        def __fspath__(self) -> str:
            return "1"

    _assert_call_attempt_timeout_type_contract(CallAttemptStart)
    valid_start = {
        "call_attempt_id": "call-1",
        "logical_action_id": "logical-1",
        "ordinal": 1,
        "request_sha256": "request-sha",
        "provider": "provider",
        "model": "model",
        "output_token_limit": 1,
    }
    for valid in (1, 1.0):
        timeout = CallAttemptStart(**valid_start, timeout_seconds=valid).timeout_seconds
        assert type(timeout) is float
        assert timeout == 1.0

    invalid_raw_values = (
        b"1",
        bytearray(b"1"),
        memoryview(b"1"),
        None,
        [1],
        (1,),
        {"value": 1},
        {1},
        complex(1, 0),
        IntSubclass(1),
        FloatSubclass(1.0),
        Path("1"),
        FloatProtocol(),
        IndexProtocol(),
        PathLikeProtocol(),
        "1.0",
        True,
        Decimal("1.0"),
        Fraction(1, 2),
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        0.0,
        -1,
        -1.0,
    )
    for invalid in invalid_raw_values:
        with pytest.raises(ValidationError):
            CallAttemptStart(**valid_start, timeout_seconds=invalid)


def test_schema_equivalent_strict_float_is_not_a_timeout_semantics_guard() -> None:
    from aeread.sdk.v1 import CallAttemptStart

    schema_equivalent_mutant = TypeAdapter(Annotated[float, Field(strict=True, gt=0)])
    timeout_schema = dict(
        CallAttemptStart.model_json_schema()["properties"]["timeout_seconds"]
    )
    timeout_schema.pop("title")
    assert schema_equivalent_mutant.json_schema() == timeout_schema

    coercion_counterexamples = (Decimal("1.0"), Fraction(1, 2), float("inf"))
    for counterexample in coercion_counterexamples:
        schema_equivalent_mutant.validate_python(counterexample)
        with pytest.raises(ValidationError):
            CallAttemptStart(
                call_attempt_id="call-1",
                logical_action_id="logical-1",
                ordinal=1,
                request_sha256="request-sha",
                provider="provider",
                model="model",
                timeout_seconds=counterexample,
                output_token_limit=1,
            )

    nonfinite_coercing_mutant = TypeAdapter(
        Annotated[
            float,
            Field(strict=True, gt=0),
            BeforeValidator(
                lambda value: (
                    1.0
                    if isinstance(value, float) and not math.isfinite(value)
                    else value
                )
            ),
        ]
    )
    assert nonfinite_coercing_mutant.json_schema() == timeout_schema
    for counterexample in (float("nan"), float("inf"), float("-inf")):
        assert nonfinite_coercing_mutant.validate_python(counterexample) == 1.0
        with pytest.raises(ValidationError):
            CallAttemptStart(
                call_attempt_id="call-1",
                logical_action_id="logical-1",
                ordinal=1,
                request_sha256="request-sha",
                provider="provider",
                model="model",
                timeout_seconds=counterexample,
                output_token_limit=1,
            )


def test_timeout_contract_rejects_the_reviewers_selective_bytes_mutant() -> None:
    from aeread.sdk.v1 import CallAttemptStart

    def accept_bytes_or_exact_number(value: object) -> object:
        if type(value) is bytes:
            return 1.0
        if type(value) not in (int, float):
            raise ValueError("expected an exact number")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("expected a finite number")
        return value

    timeout_type = Annotated[
        float,
        BeforeValidator(accept_bytes_or_exact_number),
        Field(strict=True, allow_inf_nan=False),
    ]
    selective_mutant = create_model(
        "SelectiveBytesCallAttemptStart",
        __base__=CallAttemptStart,
        timeout_seconds=(timeout_type, Field(gt=0)),
    )
    assert (
        selective_mutant.model_json_schema()["properties"]["timeout_seconds"]
        == CallAttemptStart.model_json_schema()["properties"]["timeout_seconds"]
    )
    assert (
        selective_mutant(
            call_attempt_id="call-1",
            logical_action_id="logical-1",
            ordinal=1,
            request_sha256="request-sha",
            provider="provider",
            model="model",
            timeout_seconds=b"coercion",
            output_token_limit=1,
        ).timeout_seconds
        == 1.0
    )
    try:
        _assert_call_attempt_timeout_type_contract(selective_mutant)
    except AssertionError:
        pass
    else:
        raise AssertionError(
            "selective bytes mutant escaped the timeout contract guard"
        )


def test_timeout_contract_rejects_a_mutated_sdkfloat_authority_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aeread.sdk.v1 import CallAttemptStart
    from aeread.sdk.v1 import base as sdk_base

    def accept_path_or_exact_number(value: object) -> object:
        if isinstance(value, Path):
            return 1.0
        if type(value) not in (int, float):
            raise ValueError("expected an exact number")
        if type(value) is float and not math.isfinite(value):
            raise ValueError("expected a finite number")
        return value

    mutated_sdk_float = Annotated[
        float,
        BeforeValidator(accept_path_or_exact_number),
        Field(strict=True, allow_inf_nan=False),
    ]
    monkeypatch.setattr(sdk_base, "SDKFloat", mutated_sdk_float)
    mutant_record = create_model(
        "MutatedAuthorityCallAttemptStart",
        __base__=CallAttemptStart,
        timeout_seconds=(mutated_sdk_float, Field(gt=0)),
    )
    assert (
        mutant_record.model_json_schema()["properties"]["timeout_seconds"]
        == CallAttemptStart.model_json_schema()["properties"]["timeout_seconds"]
    )
    assert (
        mutant_record(
            call_attempt_id="call-1",
            logical_action_id="logical-1",
            ordinal=1,
            request_sha256="request-sha",
            provider="provider",
            model="model",
            timeout_seconds=Path("1"),
            output_token_limit=1,
        ).timeout_seconds
        == 1.0
    )
    try:
        _assert_call_attempt_timeout_type_contract(mutant_record)
    except AssertionError:
        pass
    else:
        raise AssertionError("mutated SDKFloat authority alias escaped the guard")


def test_timeout_contract_rejects_validator_global_type_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aeread.sdk.v1 import CallAttemptStart
    from aeread.sdk.v1 import base as sdk_base

    class FloatProtocol:
        def __float__(self) -> float:
            return 1.0

    def selective_type(value: object) -> type[object]:
        if isinstance(value, FloatProtocol):
            return float
        return builtins.type(value)

    monkeypatch.setitem(
        sdk_base._require_exact_number.__globals__, "type", selective_type
    )
    accepted = CallAttemptStart(
        call_attempt_id="call-1",
        logical_action_id="logical-1",
        ordinal=1,
        request_sha256="request-sha",
        provider="provider",
        model="model",
        timeout_seconds=FloatProtocol(),
        output_token_limit=1,
    )
    assert accepted.timeout_seconds == 1.0
    try:
        _assert_call_attempt_timeout_type_contract(CallAttemptStart)
    except AssertionError:
        pass
    else:
        raise AssertionError("validator global type shadow escaped the guard")


@pytest.mark.parametrize("shadowed_builtin", ("type", "int", "float"))
def test_timeout_contract_rejects_validator_function_builtin_shadow(
    monkeypatch: pytest.MonkeyPatch,
    shadowed_builtin: str,
) -> None:
    from aeread.sdk.v1 import CallAttemptStart
    from aeread.sdk.v1 import base as sdk_base

    class FloatProtocol:
        def __float__(self) -> float:
            return 1.0

    original = sdk_base._require_exact_number
    function_builtins = dict(vars(builtins))
    if shadowed_builtin == "type":

        def selective_type(value: object) -> type[object]:
            if isinstance(value, FloatProtocol):
                return float
            return builtins.type(value)

        function_builtins[shadowed_builtin] = selective_type
    else:
        function_builtins[shadowed_builtin] = FloatProtocol
    cloned_validator = FunctionType(
        original.__code__,
        {"__builtins__": function_builtins, "__name__": original.__module__},
        original.__name__,
    )
    assert hashlib.sha256(inspect.getsource(cloned_validator).encode()).hexdigest() == (
        EXACT_NUMBER_VALIDATOR_SOURCE_SHA256
    )
    assert cloned_validator.__module__ == "aeread.sdk.v1.base"
    assert cloned_validator.__qualname__ == "_require_exact_number"
    assert cloned_validator.__closure__ is None
    assert not any(
        name in cloned_validator.__globals__ for name in ("type", "int", "float")
    )
    monkeypatch.setattr(sdk_base, "_require_exact_number", cloned_validator)
    timeout_type = Annotated[
        float,
        BeforeValidator(cloned_validator),
        Field(strict=True, allow_inf_nan=False),
    ]
    mutant_record = create_model(
        f"BuiltinShadow{shadowed_builtin.title()}CallAttemptStart",
        __base__=CallAttemptStart,
        timeout_seconds=(timeout_type, Field(gt=0)),
    )
    assert (
        mutant_record(
            call_attempt_id="call-1",
            logical_action_id="logical-1",
            ordinal=1,
            request_sha256="request-sha",
            provider="provider",
            model="model",
            timeout_seconds=FloatProtocol(),
            output_token_limit=1,
        ).timeout_seconds
        == 1.0
    )
    try:
        _assert_call_attempt_timeout_type_contract(mutant_record)
    except AssertionError:
        pass
    else:
        raise AssertionError(
            f"validator function builtin {shadowed_builtin!r} shadow escaped the guard"
        )


def test_timeout_contract_rejects_fake_finite_metadata() -> None:
    from aeread.sdk.v1 import CallAttemptStart
    from aeread.sdk.v1 import base as sdk_base

    class FakeFinite:
        allow_inf_nan = False

    fake_finite_field = Field(strict=True)
    fake_finite_field.metadata.append(FakeFinite())
    timeout_type = Annotated[
        float,
        BeforeValidator(sdk_base._require_exact_number),
        fake_finite_field,
    ]
    mutant_record = create_model(
        "FakeFiniteCallAttemptStart",
        __base__=CallAttemptStart,
        timeout_seconds=(timeout_type, Field(gt=0)),
    )
    assert mutant_record(
        call_attempt_id="call-1",
        logical_action_id="logical-1",
        ordinal=1,
        request_sha256="request-sha",
        provider="provider",
        model="model",
        timeout_seconds=float("inf"),
        output_token_limit=1,
    ).timeout_seconds == float("inf")
    try:
        _assert_call_attempt_timeout_type_contract(mutant_record)
    except AssertionError:
        pass
    else:
        raise AssertionError("fake finite metadata escaped the timeout contract guard")


def test_resolution_rejects_malformed_reference_before_lookup() -> None:
    registry = PluginRegistry.from_objects()

    with pytest.raises(UntrustedPluginReference):
        registry.resolve_environment("os:system", "1.0.0")
    with pytest.raises(UntrustedPluginReference):
        registry.resolve_environment("fake_market", "")


def test_sdk_import_does_not_load_family_or_heavy_adapter_modules() -> None:
    code = """
import sys
import aeread.sdk.v1
forbidden = (
    'aeread.exchange_economy', 'tau3', 'agenticpay', 'gurobipy',
    'vllm', 'sglang', 'docker', 'harbor',
)
assert not any(
    name == item or name.startswith(item + '.')
    for item in forbidden
    for name in sys.modules
)
assert not any(name.startswith('aeread.integrations') for name in sys.modules)
"""
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(repo_root / "src"))
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def _reference(
    implementation_id: str = "official-scorer",
    version: str = "1.0.0",
    marker: str = "1",
) -> ImplementationRef:
    return ImplementationRef(
        implementation_id=implementation_id,
        version=version,
        content_sha256=marker * 64,
    )


def _registration(
    *,
    role: str = "validity_predicate",
    ref: ImplementationRef | None = None,
    function=lambda value: value,
) -> RegisteredReferenceImplementation:
    return RegisteredReferenceImplementation(
        role=role,
        ref=ref or _reference(),
        function=function,
    )


def test_reference_implementation_registry_resolves_only_an_exact_controller_pin() -> (
    None
):
    function = lambda value: value
    ref = _reference()
    registration = _registration(ref=ref, function=function)
    registry = ReferenceImplementationRegistry.from_registrations((registration,))

    resolved = registry.resolve(ref, role="validity_predicate")
    assert resolved == registration
    assert resolved is not registration
    assert resolved.function is function


def test_reference_implementation_registry_keeps_hashes_and_roles_explicit() -> None:
    first = lambda value: value
    second = lambda value: value
    third = lambda value: value
    ref_a = _reference(marker="a")
    ref_b = _reference(marker="b")
    registry = ReferenceImplementationRegistry.from_registrations(
        (
            _registration(ref=ref_a, function=first),
            _registration(ref=ref_b, function=second),
            _registration(role="canonicalizer", ref=ref_a, function=third),
        )
    )

    assert registry.resolve(ref_a, role="validity_predicate").function is first
    assert registry.resolve(ref_b, role="validity_predicate").function is second
    assert registry.resolve(ref_a, role="canonicalizer").function is third


def test_reference_implementation_registry_rejects_duplicate_role_and_pin() -> None:
    registration = _registration()

    with pytest.raises(DuplicateReferenceImplementation):
        ReferenceImplementationRegistry.from_registrations((registration, registration))


@pytest.mark.parametrize(
    "registration",
    (
        _registration(role="not-a-role"),
        _registration(ref=_reference().model_copy(update={"implementation_id": " "})),
        _registration(ref=_reference().model_copy(update={"version": "latest"})),
        _registration(ref=_reference().model_copy(update={"content_sha256": "A" * 64})),
        _registration(ref=_reference().model_copy(update={"smuggled": "value"})),
        _registration(ref=ImplementationRef.model_construct()),
        _registration(function=object()),
    ),
)
def test_reference_implementation_registry_revalidates_admission(
    registration: RegisteredReferenceImplementation,
) -> None:
    with pytest.raises(InvalidReferenceImplementation):
        ReferenceImplementationRegistry.from_registrations((registration,))


def test_reference_implementation_registry_rejects_async_callables() -> None:
    async def async_function(value: object) -> object:
        return value

    class AsyncCallable:
        async def __call__(self, value: object) -> object:
            return value

    for function in (async_function, AsyncCallable()):
        with pytest.raises(InvalidReferenceImplementation, match="synchronous"):
            ReferenceImplementationRegistry.from_registrations(
                (_registration(function=function),)
            )


def test_reference_implementation_registry_rejects_async_generators() -> None:
    async def async_generator(value: object):
        yield value

    class AsyncGeneratorCallable:
        async def __call__(self, value: object):
            yield value

    for function in (async_generator, AsyncGeneratorCallable()):
        with pytest.raises(InvalidReferenceImplementation, match="synchronous"):
            ReferenceImplementationRegistry.from_registrations(
                (_registration(function=function),)
            )


def test_reference_implementation_registry_canonicalizes_subclass_state_once() -> None:
    sync_function = lambda value: value

    async def switched_function(value: object) -> object:
        return value

    class LyingImplementationRef(ImplementationRef):
        def __getattribute__(self, name: str) -> object:
            if name == "version":
                return "forged-after-admission"
            return super().__getattribute__(name)

    class SwitchingRegistration(RegisteredReferenceImplementation):
        def __getattribute__(self, name: str) -> object:
            if name == "function":
                reads = object.__getattribute__(self, "_function_reads")
                object.__setattr__(self, "_function_reads", reads + 1)
                if reads:
                    return switched_function
            return super().__getattribute__(name)

    lying_ref = LyingImplementationRef(
        implementation_id="official-scorer",
        version="1.0.0",
        content_sha256="1" * 64,
    )
    supplied = SwitchingRegistration(
        role="validity_predicate",
        ref=lying_ref,
        function=sync_function,
    )
    object.__setattr__(supplied, "_function_reads", 0)
    registry = ReferenceImplementationRegistry.from_registrations((supplied,))

    resolved = registry.resolve(_reference(), role="validity_predicate")

    assert type(resolved) is RegisteredReferenceImplementation
    assert type(resolved.ref) is ImplementationRef
    assert resolved.ref.version == "1.0.0"
    assert resolved.function is sync_function


def test_reference_implementation_registry_never_executes_or_reads_claims() -> None:
    calls: list[object] = []

    class Liar:
        def __getattribute__(self, name: str) -> object:
            if name in {"manifest", "implementation_id", "version", "content_sha256"}:
                raise AssertionError(f"self-claim accessed: {name}")
            return object.__getattribute__(self, name)

        def __call__(self, value: object) -> object:
            calls.append(value)
            return value

    registry = ReferenceImplementationRegistry.from_registrations(
        (_registration(function=Liar()),)
    )

    assert calls == []
    assert callable(registry.resolve(_reference(), role="validity_predicate").function)
    assert calls == []


def test_reference_implementation_registry_error_precedence_and_diagnostics() -> None:
    ref = _reference(version="1.0.0", marker="a")
    registry = ReferenceImplementationRegistry.from_registrations(
        (
            _registration(ref=ref),
            _registration(ref=_reference(version="1.0.0", marker="b")),
            _registration(ref=_reference(version="2.0.0", marker="c")),
            _registration(role="canonicalizer", ref=ref),
        )
    )

    with pytest.raises(ReferenceImplementationRoleMismatch) as role_error:
        registry.resolve(ref, role="rule_predicate")
    assert role_error.value.available_roles == (
        "canonicalizer",
        "validity_predicate",
    )

    with pytest.raises(ReferenceImplementationHashMismatch) as hash_error:
        registry.resolve(_reference(marker="d"), role="validity_predicate")
    assert hash_error.value.available_hashes == ("a" * 64, "b" * 64)

    with pytest.raises(ReferenceImplementationVersionMismatch) as version_error:
        registry.resolve(
            _reference(version="3.0.0", marker="e"),
            role="validity_predicate",
        )
    assert version_error.value.available_versions == ("1.0.0", "2.0.0")

    with pytest.raises(UnknownReferenceImplementation):
        registry.resolve(_reference("unknown"), role="validity_predicate")


@pytest.mark.parametrize(
    ("ref", "role"),
    (
        (_reference().model_copy(update={"version": "current"}), "validity_predicate"),
        (_reference().model_copy(update={"unexpected": True}), "validity_predicate"),
        (ImplementationRef.model_construct(), "validity_predicate"),
        (_reference(), "unknown-role"),
    ),
)
def test_reference_implementation_registry_revalidates_resolution_input(
    ref: ImplementationRef, role: str
) -> None:
    registry = ReferenceImplementationRegistry.from_registrations((_registration(),))

    with pytest.raises(InvalidReferenceImplementation):
        registry.resolve(ref, role=role)


def test_reference_implementation_registry_never_invokes_discovery(monkeypatch) -> None:
    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("entry-point discovery is forbidden")

    monkeypatch.setattr("aeread.runner.registry.metadata.entry_points", explode)
    registry = ReferenceImplementationRegistry.from_registrations((_registration(),))

    assert callable(registry.resolve(_reference(), role="validity_predicate").function)


def test_reference_implementation_registry_has_no_mutation_surface() -> None:
    assert not hasattr(ReferenceImplementationRegistry, "discover")
    assert not hasattr(ReferenceImplementationRegistry, "register")
    assert not hasattr(ReferenceImplementationRegistry, "list")
    assert not hasattr(ReferenceImplementationRegistry, "resolve_import_path")
    with pytest.raises((InvalidReferenceImplementation, TypeError)):
        ReferenceImplementationRegistry({})  # type: ignore[call-arg]
    registry = ReferenceImplementationRegistry.from_registrations((_registration(),))
    with pytest.raises(AttributeError):
        setattr(
            registry,
            "_ReferenceImplementationRegistry__registrations",
            {},
        )
    with pytest.raises(AttributeError):
        delattr(registry, "_ReferenceImplementationRegistry__registrations")


def test_runner_public_exports_are_the_exact_task_1_1a2_surface() -> None:
    import aeread.runner as runner

    expected = {
        "ADMISSION_REQUIREMENTS",
        "ArtifactIntegrityError",
        "ArtifactStore",
        "CapabilityMismatch",
        "ConflictingReferenceArtifactDeclaration",
        "ContentHashMismatch",
        "ConcurrentWriterError",
        "DuplicateReferenceImplementation",
        "EventIntegrityError",
        "EventStore",
        "EvidenceSealedError",
        "EvidenceStoreError",
        "IncompleteAgentAssignment",
        "InvalidAgentRequest",
        "InvalidClusterDeclaration",
        "InvalidEvidenceInput",
        "InvalidReferenceArtifactInput",
        "InvalidReferenceImplementation",
        "ManifestMismatch",
        "PlanningError",
        "PluginRegistry",
        "ReferenceArtifactError",
        "ReferenceArtifactUnavailable",
        "ReferenceArtifactView",
        "ReferenceImplementationError",
        "ReferenceImplementationHashMismatch",
        "ReferenceImplementationRegistry",
        "ReferenceImplementationRole",
        "ReferenceImplementationRoleMismatch",
        "ReferenceImplementationVersionMismatch",
        "RegisteredReferenceImplementation",
        "UndeclaredReferenceArtifact",
        "UnknownReferenceImplementation",
        "UnresolvedImplementation",
        "build_agent_request_from_plan",
        "build_reference_artifact_view",
        "evaluate_admission",
        "recompute_event_hash",
        "resolve_run_plan",
        "verify_run_plan_identity",
    }

    assert set(runner.__all__) == expected
    assert len(runner.__all__) == 40


def test_task_1_1a2_does_not_change_or_expand_the_sdk_surface() -> None:
    import aeread.sdk.v1 as sdk

    surface = tuple(sorted(sdk.__all__))
    digest = hashlib.sha256(
        json.dumps(surface, separators=(",", ":")).encode()
    ).hexdigest()

    assert len(sdk.__all__) == 158
    assert digest == "2fe7d6311a309b47d2b753381144e2e7689a11b65e9bac145162ce779565bd3b"
    for name in (
        "ReferenceArtifactView",
        "ReferenceImplementationRegistry",
        "RegisteredReferenceImplementation",
    ):
        assert not hasattr(sdk, name)


def test_task_1_1a2_does_not_publish_later_owned_binding_types() -> None:
    import aeread.runner as runner

    for name in (
        "ResolvedEvaluationBinding",
        "RaterAggregateInput",
        "ResolvedMeasurementContract",
        "ResolvedMeasurementDesign",
        "BoundVerifier",
        "ScorerInputArtifactView",
        "SuiteMeasurementBinding",
    ):
        assert not hasattr(runner, name)


def test_runner_import_with_task_1_1a2_stays_family_and_provider_free() -> None:
    code = """
import sys
import aeread.runner.registry
import aeread.runner.verifier_artifacts
forbidden = (
    'aeread.exchange_economy', 'tau3', 'agenticpay', 'gurobipy',
    'vllm', 'sglang', 'docker', 'harbor', 'openai', 'google', 'anthropic',
)
assert not any(
    name == item or name.startswith(item + '.')
    for item in forbidden
    for name in sys.modules
)
assert not any(name.startswith('aeread.integrations') for name in sys.modules)
"""
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(repo_root / "src"))

    subprocess.run([sys.executable, "-c", code], check=True, env=env)
