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


def test_registry_rejects_object_that_does_not_implement_its_category() -> None:
    with pytest.raises(IncompatiblePlugin, match="EnvironmentPlugin"):
        PluginRegistry.from_objects(environments=[MissingStepEnvironment()])


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


def test_protocols_are_runtime_checkable_and_missing_methods_are_rejected() -> None:
    assert isinstance(FakeEnvironment(), EnvironmentPlugin)
    assert isinstance(FakeVerifier(), VerifierPlugin)
    assert isinstance(FakeAgentAdapter(), AgentAdapter)
    assert isinstance(FakeAttemptObserver(), AttemptObserver)
    assert isinstance(FakeExecutionBackend(), ExecutionBackend)
    assert isinstance(FakeBenchmarkSource(), BenchmarkSourceAdapter)
    assert not isinstance(MissingStepEnvironment(), EnvironmentPlugin)


def test_protocol_method_boundaries_resolve_and_preserve_call_direction() -> None:
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
