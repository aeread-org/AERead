"""Trusted, exact-version plugin registration and entry-point discovery."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from importlib import metadata
from typing import Protocol, TypeVar, cast

from aeread.sdk.v1 import (
    AgentAdapter,
    BenchmarkSourceAdapter,
    EnvironmentPlugin,
    ExecutionBackend,
    PluginManifest,
    PluginRef,
    UntrustedPluginReference,
    VerifierPlugin,
)


class PluginRegistryError(Exception):
    """Base class for trusted-registry failures."""


class IncompatiblePlugin(PluginRegistryError):
    """A discovered object is not compatible with its declared category."""


class DuplicatePluginRegistration(PluginRegistryError):
    """A category contains two objects with the same exact plugin key."""


class UnknownPlugin(PluginRegistryError):
    """No plugin with the requested ID is registered in the category."""


class PluginVersionMismatch(PluginRegistryError):
    """A plugin ID exists, but not at the exact requested version."""

    def __init__(
        self,
        category: str,
        plugin_id: str,
        plugin_version: str,
        available_versions: tuple[str, ...],
    ) -> None:
        self.category = category
        self.plugin_id = plugin_id
        self.plugin_version = plugin_version
        self.available_versions = available_versions
        super().__init__(
            f"{category} plugin {plugin_id!r} has no exact version "
            f"{plugin_version!r}; available versions: {available_versions!r}"
        )


class _EntryPoint(Protocol):
    def load(self) -> object: ...


EntryPointsProvider = Callable[..., Sequence[_EntryPoint]]
PluginT = TypeVar("PluginT")


_GROUPS = (
    ("aeread.environments", "environments"),
    ("aeread.benchmark_sources", "benchmark_sources"),
    ("aeread.verifiers", "verifiers"),
    ("aeread.agent_adapters", "agent_adapters"),
    ("aeread.execution_backends", "execution_backends"),
)

_PROTOCOLS: dict[str, type[object]] = {
    "environments": EnvironmentPlugin,
    "benchmark_sources": BenchmarkSourceAdapter,
    "verifiers": VerifierPlugin,
    "agent_adapters": AgentAdapter,
    "execution_backends": ExecutionBackend,
}


class PluginRegistry:
    """Registry keyed by category, stable plugin ID, and exact semantic version."""

    def __init__(self) -> None:
        self._categories: dict[str, dict[tuple[str, str], object]] = {
            category: {} for _, category in _GROUPS
        }

    @classmethod
    def from_objects(
        cls,
        *,
        environments: Iterable[object] = (),
        benchmark_sources: Iterable[object] = (),
        verifiers: Iterable[object] = (),
        agent_adapters: Iterable[object] = (),
        execution_backends: Iterable[object] = (),
    ) -> "PluginRegistry":
        registry = cls()
        supplied = {
            "environments": environments,
            "benchmark_sources": benchmark_sources,
            "verifiers": verifiers,
            "agent_adapters": agent_adapters,
            "execution_backends": execution_backends,
        }
        for category, objects in supplied.items():
            for plugin in objects:
                registry._register(category, plugin)
        return registry

    @classmethod
    def discover(
        cls,
        *,
        entry_points_provider: EntryPointsProvider | None = None,
    ) -> "PluginRegistry":
        provider = entry_points_provider or metadata.entry_points
        discovered: dict[str, list[object]] = {
            category: [] for _, category in _GROUPS
        }
        for group, category in _GROUPS:
            for entry_point in provider(group=group):
                discovered[category].append(entry_point.load())
        return cls.from_objects(**discovered)

    def _register(self, category: str, plugin: object) -> None:
        manifest = getattr(plugin, "manifest", None)
        if manifest is None:
            raise IncompatiblePlugin(
                f"{category} plugin is missing a PluginManifest"
            )
        if not isinstance(manifest, PluginManifest):
            raise IncompatiblePlugin(
                f"{category} plugin manifest must be a PluginManifest"
            )
        if manifest.sdk_api != "aeread.sdk/v1":
            raise IncompatiblePlugin(
                f"{category} plugin has incompatible sdk_api {manifest.sdk_api!r}"
            )
        try:
            ref = PluginRef(
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.plugin_version,
            )
        except UntrustedPluginReference as exc:
            raise IncompatiblePlugin(
                f"{category} plugin has an invalid manifest reference"
            ) from exc

        expected_protocol = _PROTOCOLS[category]
        if not isinstance(plugin, expected_protocol):
            raise IncompatiblePlugin(
                f"{category} plugin does not implement "
                f"{expected_protocol.__name__}"
            )

        key = (ref.plugin_id, ref.plugin_version)
        if key in self._categories[category]:
            raise DuplicatePluginRegistration(
                f"duplicate {category} plugin {ref.plugin_id!r} "
                f"at version {ref.plugin_version!r}"
            )
        self._categories[category][key] = plugin

    def _resolve(
        self, category: str, plugin_id: str, plugin_version: str
    ) -> object:
        ref = PluginRef(plugin_id=plugin_id, plugin_version=plugin_version)
        registered = self._categories[category]
        key = (ref.plugin_id, ref.plugin_version)
        if key in registered:
            return registered[key]

        versions = tuple(
            sorted(
                version
                for registered_id, version in registered
                if registered_id == ref.plugin_id
            )
        )
        if versions:
            raise PluginVersionMismatch(
                category,
                ref.plugin_id,
                ref.plugin_version,
                versions,
            )
        raise UnknownPlugin(
            f"unknown {category} plugin {ref.plugin_id!r}"
        )

    def resolve_environment(
        self, plugin_id: str, plugin_version: str
    ) -> EnvironmentPlugin[object, object, object]:
        return cast(
            EnvironmentPlugin[object, object, object],
            self._resolve("environments", plugin_id, plugin_version),
        )

    def resolve_benchmark_source(
        self, plugin_id: str, plugin_version: str
    ) -> BenchmarkSourceAdapter[object, object, object, object]:
        return cast(
            BenchmarkSourceAdapter[object, object, object, object],
            self._resolve("benchmark_sources", plugin_id, plugin_version),
        )

    def resolve_verifier(
        self, plugin_id: str, plugin_version: str
    ) -> VerifierPlugin[object]:
        return cast(
            VerifierPlugin[object],
            self._resolve("verifiers", plugin_id, plugin_version),
        )

    def resolve_agent_adapter(
        self, plugin_id: str, plugin_version: str
    ) -> AgentAdapter:
        return cast(
            AgentAdapter,
            self._resolve("agent_adapters", plugin_id, plugin_version),
        )

    def resolve_execution_backend(
        self, plugin_id: str, plugin_version: str
    ) -> ExecutionBackend[object, object, object, object]:
        return cast(
            ExecutionBackend[object, object, object, object],
            self._resolve("execution_backends", plugin_id, plugin_version),
        )


__all__ = [
    "DuplicatePluginRegistration",
    "IncompatiblePlugin",
    "PluginRegistry",
    "PluginRegistryError",
    "PluginVersionMismatch",
    "UnknownPlugin",
]
