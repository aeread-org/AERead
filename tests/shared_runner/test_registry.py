from __future__ import annotations

import inspect
import os
from pathlib import Path
import subprocess
import sys
from typing import get_type_hints

import pytest

from aeread.runner.registry import (
    DuplicatePluginRegistration,
    IncompatiblePlugin,
    PluginRegistry,
    PluginVersionMismatch,
    UnknownPlugin,
)
from aeread.sdk.v1 import (
    AgentAdapter,
    AttemptObserver,
    BenchmarkSourceAdapter,
    EnvironmentPlugin,
    ExecutionBackend,
    OfficialVerifierBridge,
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
            agent_adapters=[
                BadObservabilityAgent(call_observability="provider_maybe")
            ]
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

        async def act(
            self, request: object, *, attempts: object
        ) -> object:
            return {}

    with pytest.raises(IncompatiblePlugin, match="agent_adapters") as exc_info:
        PluginRegistry.from_objects(
            agent_adapters=[RaisingObservabilityAgent()]
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_registry_wraps_raising_manifest_property() -> None:
    class RaisingManifestEnvironment:
        @property
        def manifest(self) -> object:
            raise RuntimeError("manifest exploded")

    with pytest.raises(IncompatiblePlugin, match="environments") as exc_info:
        PluginRegistry.from_objects(
            environments=[RaisingManifestEnvironment()]
        )

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
    assert registry.resolve_environment("fake_market", "1.0.0") is plugins[
        "aeread.environments"
    ]


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
    observer_hints = get_type_hints(AttemptObserver.call_started)
    bridge_hints = get_type_hints(OfficialVerifierBridge.evaluate_aeread)

    from aeread.sdk.v1 import (
        AttemptObserver as AttemptObserverType,
        CallAttemptStart,
        CallAttemptToken,
        CanonicalResponse,
        ScoreEnvelope,
        SealedEvidenceView,
    )

    assert initial_state_hints["cell"].__name__ == "PlanCellT"
    assert environment_hints["response"] is CanonicalResponse
    assert verifier_hints["evidence"] is SealedEvidenceView
    assert adapter_hints["attempts"] is AttemptObserverType
    assert adapter_hints["return"] is CanonicalResponse
    assert observer_hints["start"] is CallAttemptStart
    assert observer_hints["return"] is CallAttemptToken
    assert bridge_hints["return"] is ScoreEnvelope
    assert inspect.signature(AgentAdapter.act).parameters["attempts"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )


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
