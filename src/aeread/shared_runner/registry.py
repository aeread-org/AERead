"""Explicit trusted registries for shared-runner family plugins and harnesses.

Both registries share one discipline: no entry-point discovery, no dynamic
import, exact `(id, version)` keys, duplicate registration refused.
Deployment code decides what is trusted and registers it before R2 plan
resolution (`resolver.py`) admits a run (§5.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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


# --- Harness capability declarations and registry (§5.1, §5.3) ---
#
# These two dataclasses describe what a provider offers and what a harness
# demands.  They live here, below `resolver.py` in the import graph, so R2
# admission (`resolver.py`) can check one against the other without a
# harness ever depending on it -- `harness.py` imports both back from here.


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    native_tools: bool
    structured_output: bool
    seed: bool
    system_prompt: bool
    reasoning_budget: bool
    reasoning_token_report: bool
    max_context_tokens: int | None


@dataclass(frozen=True, slots=True)
class HarnessRequirements:
    provider: frozenset[str]
    tools: Literal["none", "declared", "any"]
    memory: frozenset[str]
    owns_retries: bool
    owns_tools: bool
    replayable: bool
    blocking: bool
    spawns_subagents: bool


class HarnessRegistryError(RuntimeError):
    """Base class for trusted harness registry failures."""


class DuplicateHarnessError(HarnessRegistryError):
    """A harness id/version key was already bound."""


class HarnessResolutionError(HarnessRegistryError):
    """A profile's harness reference did not resolve to a registered harness."""


@dataclass(frozen=True, slots=True)
class RegisteredHarness:
    harness_id: str
    harness_version: str
    harness: Any


class HarnessRegistry:
    """Resolve only harnesses explicitly registered for an exact version.

    Mirrors `PluginRegistry`: no entry-point discovery, no dynamic import,
    duplicate `(id, version)` refused.  R2 admission (`resolver.py`) resolves
    each profile's harness here before checking its `HarnessRequirements`
    against the provider it names.
    """

    def __init__(self) -> None:
        self._harnesses: dict[tuple[str, str], RegisteredHarness] = {}

    def register(self, harness: Any) -> None:
        harness_id = getattr(harness, "id", None)
        harness_version = getattr(harness, "version", None)
        if not isinstance(harness_id, str) or not harness_id.strip():
            raise HarnessRegistryError("harness.id must be a non-empty string")
        if not isinstance(harness_version, str) or not harness_version.strip():
            raise HarnessRegistryError("harness.version must be a non-empty string")
        if not isinstance(getattr(harness, "requires", None), HarnessRequirements):
            raise HarnessRegistryError(
                f"harness {harness_id}@{harness_version} has no HarnessRequirements"
            )
        key = (harness_id, harness_version)
        if key in self._harnesses:
            raise DuplicateHarnessError(
                f"harness {harness_id}@{harness_version} is already registered"
            )
        self._harnesses[key] = RegisteredHarness(
            harness_id=harness_id, harness_version=harness_version, harness=harness
        )

    def resolve(self, harness_id: str, harness_version: str) -> Any:
        registered = self._harnesses.get((harness_id, harness_version))
        if registered is None:
            raise HarnessResolutionError(
                f"harness {harness_id}@{harness_version} is not registered"
            )
        return registered.harness

    def registrations(self) -> tuple[RegisteredHarness, ...]:
        """Return a deterministic immutable snapshot for preflight diagnostics."""
        return tuple(self._harnesses[key] for key in sorted(self._harnesses))


__all__ = [
    "DuplicateHarnessError",
    "DuplicatePluginError",
    "HarnessRegistry",
    "HarnessRegistryError",
    "HarnessRequirements",
    "HarnessResolutionError",
    "IncompletePluginError",
    "PluginRegistry",
    "PluginRegistryError",
    "PluginResolutionError",
    "ProviderCapabilities",
    "REQUIRED_FAMILY_PLUGIN_HOOKS",
    "RegisteredHarness",
    "RegisteredPlugin",
]
