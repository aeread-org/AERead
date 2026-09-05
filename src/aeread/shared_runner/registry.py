"""Explicit trusted registries for shared-runner family plugins and harnesses.

Both registries share one discipline: no entry-point discovery, no dynamic
import, exact `(id, version)` keys, duplicate registration refused.
Deployment code decides what is trusted and registers it before R2 plan
resolution (`resolver.py`) admits a run (§5.3).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from .quality import (
    FamilyContribution,
    QCContractError,
    ResourceLimits,
    evidence_coverage_complete,
    verify_qc_evidence_files,
)
from .schemas import FamilyManifest, MeasurementDeclaration


class PluginRegistryError(RuntimeError):
    """Base class for trusted family-plugin registry failures."""


class DuplicatePluginError(PluginRegistryError):
    """A family/version key was already bound."""


class IncompletePluginError(PluginRegistryError):
    """A plugin does not expose the complete family-owned hook boundary."""


class PluginResolutionError(PluginRegistryError):
    """A manifest could not resolve to the exact registered implementation."""


class ContributionAdmissionError(PluginRegistryError):
    """A contributed family lacks one of the mandatory safety contracts."""


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

TRUSTED_BUILTIN_PLUGIN_KEYS = frozenset(
    {
        # External-benchmark adapter families accepted by maintainer ruling on
        # 2026-09-04 (PRs #28-#38); their review predates contribution records.
        ('agenticpay.bilateral', '0.1.0', 'agenticpay_bilateral_environment'),
        ('alympics.wac', '0.1.0', 'alympics_wac_environment'),
        ('amazonbarg.bilateral', '0.1.0', 'amazonbarg_environment'),
        ('aucarena', '0.1.0', 'aucarena_environment'),
        ('collusion', '0.1.0', 'collusion_environment'),
        ('econagent_v1', '0.1.0', 'econagent_v1_environment'),
        ('econevals', '0.1.0', 'econevals_environment'),
        ('govsim', '0.1.0', 'govsim_environment'),
        ('negarena', '0.1.0', 'negarena_environment'),
        ('steer', '0.1.0', 'steer_environment'),
        ('termsbench', '0.1.0', 'termsbench_environment'),
        (
            "commercial_state_calibration_v1",
            "1.0.0",
            "commercial_state_calibration_environment",
        ),
        ("consent_ir_v1", "1.0.0", "consent_ir_environment"),
        (
            "datacenter_development_v1",
            "1.0.0",
            "datacenter_development_environment",
        ),
        (
            "datacenter_development_v1",
            "1.1.0",
            "datacenter_development_environment_v1",
        ),
        (
            "datacenter_development_v1",
            "2.0.0",
            "datacenter_development_environment_v2",
        ),
        ("housing_v1", "1.0.0", "aeread.housing_v1"),
        (
            "procurement_allocation_v1",
            "1.0.0",
            "procurement_allocation_environment",
        ),
        (
            "procurement_grounding_v1",
            "1.0.0",
            "procurement_grounding_environment",
        ),
        ("single_offer_v1", "1.0.0", "aeread.single_offer_v1"),
        ("tau3.retail", "0.1.0", "tau3_retail_environment"),
        # Kernel-owned fixture for the scoring-contract protocol test
        # (kernel_scoring_contract_spec.md section 6). It is not a family
        # benchmark: it exists solely so that test can exercise a genuine
        # trajectory-scoped leaf against two fixtures with a byte-identical
        # terminal outcome and a differing trajectory -- a pairing none of
        # the real registered families can produce today, since each of
        # theirs is either terminal-state-scoped only or (as measured for
        # datacenter_development_v1) accumulates its full ordered history
        # into the outcome itself, making its outcome a function of its
        # trajectory and the two byte-identical-but-differing fixtures the
        # contract test requires impossible to construct honestly.
        (
            "kernel_contract_reference_v1",
            "1.0.0",
            "kernel_contract_reference_plugin",
        ),
        # Kernel-owned fixture for replay-fidelity regression tests
        # (kernel_contract_impl_review.md findings 2 and 3). No family
        # registered on ``main`` declares a ``mode="sequential"`` phase, so
        # this minimal two-actor family exists purely so
        # ``test_shared_runner_family_scoring_input_sequential.py`` can drive
        # a genuine sequential phase instance -- one with more than one
        # ``transition_applied`` event -- through the real scheduler and
        # assert ``replay_family_scoring_input`` reproduces it exactly.
        (
            "kernel_contract_sequential_v1",
            "1.0.0",
            "kernel_contract_sequential_plugin",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class RegisteredPlugin:
    family_id: str
    family_version: str
    plugin_id: str
    registry_namespace: str
    contribution_sha256: str | None
    resource_limits: ResourceLimits | None
    plugin: Any
    manifest: FamilyManifest


def _strict_schema(schema: Mapping[str, Any], label: str) -> None:
    """Require closed object shapes throughout a contributed JSON schema."""

    def visit(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            raise ContributionAdmissionError(f"{path} must be an object")
        node_type = node.get("type")
        if node_type == "object":
            properties = node.get("properties")
            required = node.get("required")
            if not isinstance(properties, Mapping):
                raise ContributionAdmissionError(
                    f"{path}.properties must be an object"
                )
            if node.get("additionalProperties") is not False:
                raise ContributionAdmissionError(
                    f"{path}.additionalProperties must be false"
                )
            if not isinstance(required, (list, tuple)):
                raise ContributionAdmissionError(
                    f"{path}.required must list every property"
                )
            if (
                len(required) != len(set(required))
                or set(required) != set(properties)
            ):
                raise ContributionAdmissionError(
                    f"{path}.required must equal the property names"
                )
            for name, child in properties.items():
                if not isinstance(name, str) or not name:
                    raise ContributionAdmissionError(
                        f"{path}.properties keys must be non-empty strings"
                    )
                visit(child, f"{path}.properties.{name}")
        elif node_type == "array":
            if "items" not in node:
                raise ContributionAdmissionError(f"{path}.items is required")
            visit(node["items"], f"{path}.items")
        elif node_type is None and not any(
            key in node for key in ("anyOf", "oneOf", "allOf", "$ref")
        ):
            raise ContributionAdmissionError(
                f"{path} must declare type or a schema composition"
            )
        for keyword in ("anyOf", "oneOf", "allOf"):
            if keyword in node:
                branches = node[keyword]
                if not isinstance(branches, (list, tuple)) or not branches:
                    raise ContributionAdmissionError(
                        f"{path}.{keyword} must be a non-empty array"
                    )
                for index, branch in enumerate(branches):
                    visit(branch, f"{path}.{keyword}[{index}]")
        definitions = node.get("$defs")
        if definitions is not None:
            if not isinstance(definitions, Mapping):
                raise ContributionAdmissionError(f"{path}.$defs must be an object")
            for name, definition in definitions.items():
                visit(definition, f"{path}.$defs.{name}")

    visit(schema, label)
    if schema.get("type") != "object":
        raise ContributionAdmissionError(f"{label} root type must be object")


def family_contribution_sha256(contribution: FamilyContribution) -> str:
    """Digest the contribution contract that the human approval must bind."""

    if not isinstance(contribution, FamilyContribution):
        raise ContributionAdmissionError(
            "contribution must be a FamilyContribution"
        )
    core = {
        "family_id": contribution.family_id,
        "family_version": contribution.family_version,
        "plugin_id": contribution.plugin_id,
        "registry_namespace": contribution.registry_namespace,
        "action_schema": contribution.action_schema,
        "observation_schema": contribution.observation_schema,
        "provider_free_evidence": contribution.provider_free_evidence,
        "resource_limits": contribution.resource_limits,
    }
    def canonical(value: Any) -> Any:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: canonical(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [canonical(item) for item in value]
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        raise ContributionAdmissionError(
            f"unsupported contribution value: {type(value).__name__}"
        )

    payload = json.dumps(
        canonical(core),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PluginRegistry:
    """Resolve only plugins explicitly registered for an exact family version.

    The registry intentionally performs no entry-point discovery or dynamic
    imports.  Deployment code decides which implementations are trusted and
    registers them before R2 plan resolution.
    """

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], RegisteredPlugin] = {}
        self._namespaces: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _validate_plugin(manifest: FamilyManifest, plugin: Any) -> None:
        if not isinstance(manifest, FamilyManifest):
            raise TypeError("manifest must be a validated FamilyManifest")
        # kernel_contract_gap_review.md finding 8: ``FamilyManifest`` has no
        # ``__post_init__``, so ``dataclasses.replace(manifest,
        # measurement=<anything>)`` previously reached this point -- and
        # registered successfully -- with ``measurement`` holding a value
        # that was never validated at all, not merely one whose leaf policy
        # was inconsistent. Every construction path that produces a
        # ``FamilyManifest`` this registry is willing to trust must still
        # carry an actually-validated ``MeasurementDeclaration``.
        if not isinstance(manifest.measurement, MeasurementDeclaration):
            raise TypeError(
                "manifest.measurement must be a validated MeasurementDeclaration"
            )
        missing = [
            hook
            for hook in REQUIRED_FAMILY_PLUGIN_HOOKS
            if not callable(getattr(plugin, hook, None))
        ]
        if missing:
            raise IncompletePluginError(
                "family plugin is missing callable hooks: " + ", ".join(missing)
            )

    def _register(
        self,
        manifest: FamilyManifest,
        plugin: Any,
        *,
        registry_namespace: str,
        contribution_sha256: str | None,
        resource_limits: ResourceLimits | None,
    ) -> None:
        self._validate_plugin(manifest, plugin)
        identity = manifest.family
        key = (identity.id, identity.version)
        if key in self._plugins:
            raise DuplicatePluginError(
                f"family plugin {identity.id}@{identity.version} is already registered"
            )
        existing_namespace = self._namespaces.get(registry_namespace)
        if existing_namespace is not None:
            raise DuplicatePluginError(
                f"registry namespace {registry_namespace!r} is already bound to "
                f"{existing_namespace[0]}@{existing_namespace[1]}"
            )
        self._plugins[key] = RegisteredPlugin(
            family_id=identity.id,
            family_version=identity.version,
            plugin_id=identity.plugin_id,
            registry_namespace=registry_namespace,
            contribution_sha256=contribution_sha256,
            resource_limits=resource_limits,
            plugin=plugin,
            manifest=manifest,
        )
        self._namespaces[registry_namespace] = key

    def register(
        self,
        manifest: FamilyManifest,
        plugin: Any,
        *,
        contribution: FamilyContribution,
        evidence_root: Path,
    ) -> None:
        """Register a new family only after every contribution gate passes."""

        if not isinstance(manifest, FamilyManifest):
            raise TypeError("manifest must be a validated FamilyManifest")
        if not isinstance(contribution, FamilyContribution):
            raise ContributionAdmissionError(
                "new family registration requires a FamilyContribution"
            )
        identity = manifest.family
        if (
            contribution.family_id,
            contribution.family_version,
            contribution.plugin_id,
        ) != (identity.id, identity.version, identity.plugin_id):
            raise ContributionAdmissionError(
                "contribution identity does not match the family manifest"
            )
        try:
            provider_identity = (
                contribution.provider_free_evidence.family_id,
                contribution.provider_free_evidence.family_version,
                contribution.provider_free_evidence.profile_id,
            )
            approval_identity = (
                contribution.human_qc_approval.evidence.family_id,
                contribution.human_qc_approval.evidence.family_version,
                contribution.human_qc_approval.evidence.profile_id,
            )
            expected_identity = (
                identity.id,
                identity.version,
                identity.id,
            )
            if provider_identity != expected_identity or approval_identity != expected_identity:
                raise ContributionAdmissionError(
                    "contribution evidence must bind the exact family, version, "
                    "and family profile"
                )
            if (
                contribution.provider_free_evidence.artifact_type
                != "provider_free_conformance"
            ):
                raise ContributionAdmissionError(
                    "provider-free evidence artifact_type must be "
                    "provider_free_conformance"
                )
            if not evidence_coverage_complete(
                (contribution.provider_free_evidence,),
                "provider_free_validation",
            ):
                raise ContributionAdmissionError(
                    "provider-free conformance coverage is incomplete"
                )
            if not evidence_coverage_complete(
                (contribution.human_qc_approval.evidence,), "human_qc"
            ):
                raise ContributionAdmissionError(
                    "human QC approval coverage is incomplete"
                )
            verify_qc_evidence_files(
                (contribution.provider_free_evidence,),
                evidence_root,
                expected_artifact_types=("provider_free_conformance",),
            )
            verify_qc_evidence_files(
                (contribution.human_qc_approval.evidence,),
                evidence_root,
                expected_artifact_types=("human_qc_approval",),
            )
        except QCContractError as error:
            raise ContributionAdmissionError(str(error)) from error
        _strict_schema(contribution.action_schema, "action_schema")
        _strict_schema(contribution.observation_schema, "observation_schema")
        digest = family_contribution_sha256(contribution)
        if contribution.human_qc_approval.contribution_sha256 != digest:
            raise ContributionAdmissionError(
                "human QC approval does not bind this contribution digest"
            )
        self._register(
            manifest,
            plugin,
            registry_namespace=contribution.registry_namespace,
            contribution_sha256=digest,
            resource_limits=contribution.resource_limits,
        )

    def register_trusted(self, manifest: FamilyManifest, plugin: Any) -> None:
        """Register an in-tree family whose review predates contribution records."""

        if not isinstance(manifest, FamilyManifest):
            raise TypeError("manifest must be a validated FamilyManifest")
        identity = manifest.family
        key = (identity.id, identity.version, identity.plugin_id)
        if key not in TRUSTED_BUILTIN_PLUGIN_KEYS:
            raise ContributionAdmissionError(
                f"family plugin {identity.id}@{identity.version} is not an "
                "exact in-tree trusted plugin; "
                "use qualified registration"
            )
        namespace = f"builtin.{identity.id}.{identity.version}"
        self._register(
            manifest,
            plugin,
            registry_namespace=namespace,
            contribution_sha256=None,
            resource_limits=None,
        )

    def resolve(
        self, family_id: str, family_version: str, plugin_id: str
    ) -> Any:
        return self.resolve_registration(
            family_id, family_version, plugin_id
        ).plugin

    def resolve_registration(
        self, family_id: str, family_version: str, plugin_id: str
    ) -> RegisteredPlugin:
        """Resolve a plugin together with its admission and limit metadata."""

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
        return registered

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


REQUIRED_HARNESS_HOOKS = (
    "open_episode",
    "act",
    "close_episode",
    "classify_failure",
)


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
        requires = getattr(harness, "requires", None)
        if not isinstance(requires, HarnessRequirements):
            raise HarnessRegistryError(
                f"harness {harness_id}@{harness_version} has no HarnessRequirements"
            )
        missing = [
            hook
            for hook in REQUIRED_HARNESS_HOOKS
            if not callable(getattr(harness, hook, None))
        ]
        # state_reader is part of the protocol only when the harness declares
        # memory beyond "disabled" (Harness protocol, section 10).
        if requires.memory != frozenset({"disabled"}) and not callable(
            getattr(harness, "state_reader", None)
        ):
            missing.append("state_reader")
        if missing:
            raise HarnessRegistryError(
                f"harness {harness_id}@{harness_version} is missing callable "
                "protocol hooks: " + ", ".join(missing)
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
    "ContributionAdmissionError",
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
    "REQUIRED_HARNESS_HOOKS",
    "TRUSTED_BUILTIN_PLUGIN_KEYS",
    "RegisteredHarness",
    "RegisteredPlugin",
    "family_contribution_sha256",
]
