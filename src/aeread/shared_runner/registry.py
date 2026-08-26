"""Explicit trusted registry for shared-runner family plugins."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import FamilyManifest


class PluginRegistryError(RuntimeError):
    """Base class for trusted family-plugin registry failures."""


class DuplicatePluginError(PluginRegistryError):
    """A family/version key was already bound."""


class IncompletePluginError(PluginRegistryError):
    """A plugin does not expose the complete family-owned hook boundary."""


class PluginResolutionError(PluginRegistryError):
    """A manifest could not resolve to the exact registered implementation."""


REQUIRED_FAMILY_PLUGIN_HOOKS = (
    "validate_payload",
    "initial_state",
    "phases",
    "eligible_actors",
    "observe",
    "parse_action",
    "legal",
    "step",
    "terminal",
    "outcome",
    "build_scorer",
    "build_reference_providers",
    "generator",
)


@dataclass(frozen=True, slots=True)
class RegisteredPlugin:
    family_id: str
    family_version: str
    plugin_id: str
    plugin: Any


class PluginRegistry:
    """Resolve only plugins explicitly registered for an exact family version.

    The registry intentionally performs no entry-point discovery or dynamic
    imports.  Deployment code decides which implementations are trusted and
    registers them before R2 plan resolution.
    """

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], RegisteredPlugin] = {}

    def register(self, manifest: FamilyManifest, plugin: Any) -> None:
        if not isinstance(manifest, FamilyManifest):
            raise TypeError("manifest must be a validated FamilyManifest")
        missing = [
            hook
            for hook in REQUIRED_FAMILY_PLUGIN_HOOKS
            if not callable(getattr(plugin, hook, None))
        ]
        if missing:
            raise IncompletePluginError(
                "family plugin is missing callable hooks: " + ", ".join(missing)
            )

        identity = manifest.family
        key = (identity.id, identity.version)
        if key in self._plugins:
            raise DuplicatePluginError(
                f"family plugin {identity.id}@{identity.version} is already registered"
            )
        self._plugins[key] = RegisteredPlugin(
            family_id=identity.id,
            family_version=identity.version,
            plugin_id=identity.plugin_id,
            plugin=plugin,
        )

    def resolve(
        self, family_id: str, family_version: str, plugin_id: str
    ) -> Any:
        key = (family_id, family_version)
        registered = self._plugins.get(key)
        if registered is None:
            raise PluginResolutionError(
                f"family plugin {family_id}@{family_version} is not registered"
            )
        if registered.plugin_id != plugin_id:
            raise PluginResolutionError(
                "registered plugin_id mismatch for "
                f"{family_id}@{family_version}: expected {registered.plugin_id!r}, "
                f"got {plugin_id!r}"
            )
        return registered.plugin

    def resolve_manifest(self, manifest: FamilyManifest) -> Any:
        if not isinstance(manifest, FamilyManifest):
            raise TypeError("manifest must be a validated FamilyManifest")
        identity = manifest.family
        return self.resolve(identity.id, identity.version, identity.plugin_id)

    def registrations(self) -> tuple[RegisteredPlugin, ...]:
        """Return a deterministic immutable snapshot for preflight diagnostics."""
        return tuple(self._plugins[key] for key in sorted(self._plugins))


__all__ = [
    "DuplicatePluginError",
    "IncompletePluginError",
    "PluginRegistry",
    "PluginRegistryError",
    "PluginResolutionError",
    "REQUIRED_FAMILY_PLUGIN_HOOKS",
    "RegisteredPlugin",
]
