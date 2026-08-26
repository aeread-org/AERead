"""Trusted, exact-version plugin registration and entry-point discovery."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata
import inspect
from types import MappingProxyType
from typing import Literal, Protocol, TypeVar, cast

from pydantic import ValidationError

from aeread.sdk.v1 import (
    AgentAdapter,
    BenchmarkSourceAdapter,
    EnvironmentPlugin,
    ExecutionBackend,
    ImplementationRef,
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


ReferenceImplementationRole = Literal[
    "validity_predicate",
    "pre_outcome_computation",
    "canonicalizer",
    "canonical_membership",
    "terminal_state_equivalence",
    "canonical_distance",
    "rule_predicate",
    "rule_relation",
    "comparative_comparator",
    "rater_projection",
    "rater_renderer",
    "imported_human_validator",
    "blind_order",
]


class ReferenceImplementationError(Exception):
    """Base error for explicit reference-implementation registrations."""


class InvalidReferenceImplementation(ReferenceImplementationError):
    """A supplied role, pin, or callable is invalid."""


class DuplicateReferenceImplementation(ReferenceImplementationError):
    """The same role and full implementation pin was supplied twice."""


class UnknownReferenceImplementation(ReferenceImplementationError):
    """No supplied implementation has the requested implementation ID."""


class ReferenceImplementationRoleMismatch(ReferenceImplementationError):
    """An implementation ID exists, but not under the requested role."""

    def __init__(
        self,
        implementation_id: str,
        role: ReferenceImplementationRole,
        available_roles: tuple[ReferenceImplementationRole, ...],
    ) -> None:
        self.implementation_id = implementation_id
        self.role = role
        self.available_roles = available_roles
        super().__init__(
            f"reference implementation {implementation_id!r} is not registered "
            f"for role {role!r}; available roles: {available_roles!r}"
        )


class ReferenceImplementationVersionMismatch(ReferenceImplementationError):
    """An implementation ID and role exist, but not at the requested version."""

    def __init__(
        self,
        implementation_id: str,
        role: ReferenceImplementationRole,
        version: str,
        available_versions: tuple[str, ...],
    ) -> None:
        self.implementation_id = implementation_id
        self.role = role
        self.version = version
        self.available_versions = available_versions
        super().__init__(
            f"reference implementation {implementation_id!r} for role {role!r} "
            f"has no exact version {version!r}; available versions: "
            f"{available_versions!r}"
        )


class ReferenceImplementationHashMismatch(ReferenceImplementationError):
    """An implementation ID, role, and version exist with other hashes."""

    def __init__(
        self,
        implementation_id: str,
        role: ReferenceImplementationRole,
        version: str,
        content_sha256: str,
        available_hashes: tuple[str, ...],
    ) -> None:
        self.implementation_id = implementation_id
        self.role = role
        self.version = version
        self.content_sha256 = content_sha256
        self.available_hashes = available_hashes
        super().__init__(
            f"reference implementation {implementation_id!r} for role {role!r} "
            f"at version {version!r} has no exact content hash "
            f"{content_sha256!r}; available hashes: {available_hashes!r}"
        )


@dataclass(frozen=True, slots=True)
class RegisteredReferenceImplementation:
    role: ReferenceImplementationRole
    ref: ImplementationRef
    function: Callable[..., object]


_REFERENCE_IMPLEMENTATION_ROLES = frozenset(
    (
        "validity_predicate",
        "pre_outcome_computation",
        "canonicalizer",
        "canonical_membership",
        "terminal_state_equivalence",
        "canonical_distance",
        "rule_predicate",
        "rule_relation",
        "comparative_comparator",
        "rater_projection",
        "rater_renderer",
        "imported_human_validator",
        "blind_order",
    )
)
_SYMBOLIC_REFERENCE_VERSIONS = frozenset(("latest", "current", "default", "stable"))
_REFERENCE_REGISTRY_TOKEN = object()


def _validate_reference_role(value: object) -> ReferenceImplementationRole:
    if type(value) is not str or value not in _REFERENCE_IMPLEMENTATION_ROLES:
        raise InvalidReferenceImplementation(
            "reference implementation role must be a supported exact string"
        )
    return cast(ReferenceImplementationRole, value)


def _validate_implementation_ref(value: object) -> ImplementationRef:
    if not isinstance(value, ImplementationRef):
        raise InvalidReferenceImplementation(
            "reference implementation pin must be an ImplementationRef"
        )
    try:
        raw_state = dict(vars(value))
        pydantic_extra = getattr(value, "__pydantic_extra__", None)
        if pydantic_extra:
            raw_state.update(pydantic_extra)
        checked = ImplementationRef.model_validate(raw_state)
    except Exception as exc:
        raise InvalidReferenceImplementation(
            "reference implementation pin is malformed"
        ) from exc
    if not checked.implementation_id.strip():
        raise InvalidReferenceImplementation(
            "reference implementation ID must be non-empty"
        )
    version = checked.version.strip()
    if not version or version.lower() in _SYMBOLIC_REFERENCE_VERSIONS:
        raise InvalidReferenceImplementation(
            "reference implementation version must be an exact non-symbolic pin"
        )
    return checked


def _validate_reference_callable(value: object) -> Callable[..., object]:
    if not callable(value):
        raise InvalidReferenceImplementation(
            "reference implementation must be callable"
        )
    call_method = getattr(type(value), "__call__", None)
    if (
        inspect.iscoroutinefunction(value)
        or inspect.iscoroutinefunction(call_method)
        or inspect.isasyncgenfunction(value)
        or inspect.isasyncgenfunction(call_method)
    ):
        raise InvalidReferenceImplementation(
            "reference implementation must be synchronous"
        )
    return cast(Callable[..., object], value)


class ReferenceImplementationRegistry:
    """Exact lookup over controller-supplied, fully pinned reference callables."""

    __slots__ = ("__registrations",)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ReferenceImplementationRegistry is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ReferenceImplementationRegistry is immutable")

    def __init__(
        self,
        registrations: dict[
            tuple[ReferenceImplementationRole, str, str, str],
            RegisteredReferenceImplementation,
        ],
        *,
        _private_token: object,
    ) -> None:
        if _private_token is not _REFERENCE_REGISTRY_TOKEN:
            raise InvalidReferenceImplementation(
                "reference implementation registry must be built by its factory"
            )
        object.__setattr__(
            self,
            "_ReferenceImplementationRegistry__registrations",
            MappingProxyType(dict(registrations)),
        )

    @classmethod
    def from_registrations(
        cls,
        registrations: Iterable[RegisteredReferenceImplementation],
    ) -> "ReferenceImplementationRegistry":
        admitted: dict[
            tuple[ReferenceImplementationRole, str, str, str],
            RegisteredReferenceImplementation,
        ] = {}
        try:
            supplied = tuple(registrations)
        except Exception as exc:
            raise InvalidReferenceImplementation(
                "reference implementation registrations are not iterable"
            ) from exc
        for registration in supplied:
            if not isinstance(registration, RegisteredReferenceImplementation):
                raise InvalidReferenceImplementation(
                    "registration must be a RegisteredReferenceImplementation"
                )
            role = _validate_reference_role(registration.role)
            ref = _validate_implementation_ref(registration.ref)
            function = _validate_reference_callable(registration.function)
            key = (
                role,
                ref.implementation_id,
                ref.version,
                ref.content_sha256,
            )
            if key in admitted:
                raise DuplicateReferenceImplementation(
                    f"duplicate reference implementation for role {role!r}, "
                    f"ID {ref.implementation_id!r}, version {ref.version!r}, "
                    f"and content hash {ref.content_sha256!r}"
                )
            admitted[key] = RegisteredReferenceImplementation(
                role=role,
                ref=ref,
                function=function,
            )
        return cls(admitted, _private_token=_REFERENCE_REGISTRY_TOKEN)

    def resolve(
        self,
        ref: ImplementationRef,
        *,
        role: ReferenceImplementationRole,
    ) -> RegisteredReferenceImplementation:
        checked_role = _validate_reference_role(role)
        checked_ref = _validate_implementation_ref(ref)
        full_key = (
            checked_role,
            checked_ref.implementation_id,
            checked_ref.version,
            checked_ref.content_sha256,
        )
        exact = self.__registrations.get(full_key)
        if exact is not None:
            return exact

        matching_full_ref_roles = tuple(
            sorted(
                cast(ReferenceImplementationRole, registered_role)
                for registered_role, implementation_id, version, digest in self.__registrations
                if (
                    implementation_id,
                    version,
                    digest,
                )
                == (
                    checked_ref.implementation_id,
                    checked_ref.version,
                    checked_ref.content_sha256,
                )
            )
        )
        if matching_full_ref_roles:
            raise ReferenceImplementationRoleMismatch(
                checked_ref.implementation_id,
                checked_role,
                matching_full_ref_roles,
            )

        matching_hashes = tuple(
            sorted(
                digest
                for registered_role, implementation_id, version, digest in self.__registrations
                if (
                    registered_role,
                    implementation_id,
                    version,
                )
                == (
                    checked_role,
                    checked_ref.implementation_id,
                    checked_ref.version,
                )
            )
        )
        if matching_hashes:
            raise ReferenceImplementationHashMismatch(
                checked_ref.implementation_id,
                checked_role,
                checked_ref.version,
                checked_ref.content_sha256,
                matching_hashes,
            )

        matching_versions = tuple(
            sorted(
                {
                    version
                    for registered_role, implementation_id, version, _ in self.__registrations
                    if (
                        registered_role,
                        implementation_id,
                    )
                    == (checked_role, checked_ref.implementation_id)
                }
            )
        )
        if matching_versions:
            raise ReferenceImplementationVersionMismatch(
                checked_ref.implementation_id,
                checked_role,
                checked_ref.version,
                matching_versions,
            )

        matching_id_roles = tuple(
            sorted(
                {
                    cast(ReferenceImplementationRole, registered_role)
                    for registered_role, implementation_id, _, _ in self.__registrations
                    if implementation_id == checked_ref.implementation_id
                }
            )
        )
        if matching_id_roles:
            raise ReferenceImplementationRoleMismatch(
                checked_ref.implementation_id,
                checked_role,
                matching_id_roles,
            )
        raise UnknownReferenceImplementation(
            f"unknown reference implementation {checked_ref.implementation_id!r}"
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

_SYNC_METHODS: dict[str, dict[str, tuple[str, ...]]] = {
    "environments": {
        "validate_case": ("payload",),
        "initial_state": ("case", "cell"),
        "phase_graph": ("case",),
        "decision_slots": ("case", "state", "phase"),
        "observe": ("case", "state", "phase", "slot"),
        "parse_action": ("case", "state", "phase", "slot", "response"),
        "legal": ("case", "state", "phase", "bundle"),
        "step": ("case", "state", "phase", "bundles"),
        "terminal": ("case", "state"),
        "outcome": ("case", "terminal"),
    },
    "benchmark_sources": {
        "source_ref": (),
        "enumerate_cases": ("split",),
        "materialize_case": ("ref",),
        "parity_fixtures": (),
    },
    "verifiers": {
        "score": ("case", "outcome", "evidence"),
    },
}

_ASYNC_METHODS: dict[str, dict[str, tuple[str, ...]]] = {
    "agent_adapters": {"act": ("request",)},
    "execution_backends": {
        "start": ("spec",),
        "run": ("handle", "request"),
        "read": ("handle", "path"),
        "write": ("handle", "path", "data"),
        "stop": ("handle",),
    },
}


_MISSING = object()


def _read_plugin_attribute(
    category: str,
    plugin: object,
    attribute: str,
    default: object = _MISSING,
) -> object:
    try:
        if default is _MISSING:
            return getattr(plugin, attribute)
        return getattr(plugin, attribute, default)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin attribute {attribute!r} could not be inspected"
        ) from exc


def _validated_manifest(category: str, plugin: object) -> PluginManifest:
    manifest = _read_plugin_attribute(category, plugin, "manifest", None)
    if manifest is None:
        raise IncompatiblePlugin(
            f"{category} plugin is missing a PluginManifest"
        )
    try:
        is_manifest = isinstance(manifest, PluginManifest)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin manifest type could not be inspected"
        ) from exc
    if not is_manifest:
        raise IncompatiblePlugin(
            f"{category} plugin manifest must be a PluginManifest"
        )

    # model_copy(update=...) deliberately skips validation and model_dump()
    # omits undeclared copied attributes. Reconstruct from the raw field state
    # so neither invalid declared fields nor smuggled extras survive admission.
    try:
        raw_state = dict(vars(manifest))
        pydantic_extra = getattr(manifest, "__pydantic_extra__", None)
        if pydantic_extra:
            raw_state.update(pydantic_extra)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin manifest state could not be inspected"
        ) from exc
    try:
        return PluginManifest.model_validate(raw_state)
    except ValidationError as exc:
        raise IncompatiblePlugin(
            f"{category} plugin has an invalid manifest: {exc}"
        ) from exc


def _validate_callable(
    category: str,
    plugin: object,
    method_name: str,
    positional_names: tuple[str, ...],
    *,
    must_be_async: bool,
    keyword_only_names: tuple[str, ...] = (),
) -> None:
    method = _read_plugin_attribute(category, plugin, method_name)
    if not callable(method):
        raise IncompatiblePlugin(
            f"{category} plugin {method_name} must be callable"
        )
    try:
        is_async = inspect.iscoroutinefunction(method)
        signature = inspect.signature(method)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin {method_name} has an uninspectable signature"
        ) from exc
    if is_async is not must_be_async:
        expected = "async" if must_be_async else "synchronous"
        raise IncompatiblePlugin(
            f"{category} plugin {method_name} must be {expected}"
        )

    parameters = signature.parameters
    for name in keyword_only_names:
        parameter = parameters.get(name)
        if parameter is None or parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
            raise IncompatiblePlugin(
                f"{category} plugin {method_name} requires keyword-only {name}"
            )

    positional_values = {name: object() for name in positional_names}
    keyword_values = {name: object() for name in keyword_only_names}
    try:
        bound = signature.bind(*positional_values.values(), **keyword_values)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin {method_name} has an incompatible signature: {exc}"
        ) from exc

    expected_by_identity = {
        id(value): name for name, value in positional_values.items()
    }
    for parameter_name, value in bound.arguments.items():
        parameter = parameters[parameter_name]
        if parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD:
            continue
        expected_name = expected_by_identity.get(id(value))
        if (
            expected_name is not None
            and parameter_name in positional_names
            and parameter_name != expected_name
        ):
            raise IncompatiblePlugin(
                f"{category} plugin {method_name} reorders explicit argument "
                f"{parameter_name!r}; runner supplies {expected_name!r} there"
            )


def _validate_contract(category: str, plugin: object) -> None:
    expected_protocol = _PROTOCOLS[category]
    try:
        conforms = isinstance(plugin, expected_protocol)
    except Exception as exc:
        raise IncompatiblePlugin(
            f"{category} plugin protocol surface could not be inspected"
        ) from exc
    if not conforms:
        raise IncompatiblePlugin(
            f"{category} plugin does not implement "
            f"{expected_protocol.__name__}"
        )

    for method_name, positional_names in _SYNC_METHODS.get(category, {}).items():
        _validate_callable(
            category,
            plugin,
            method_name,
            positional_names,
            must_be_async=False,
        )
    for method_name, positional_names in _ASYNC_METHODS.get(category, {}).items():
        keyword_only_names = ("attempts",) if method_name == "act" else ()
        _validate_callable(
            category,
            plugin,
            method_name,
            positional_names,
            must_be_async=True,
            keyword_only_names=keyword_only_names,
        )

    if category == "agent_adapters":
        observability = _read_plugin_attribute(
            category, plugin, "call_observability", None
        )
        if type(observability) is not str or observability not in (
            "full",
            "logical_only",
            "opaque",
        ):
            raise IncompatiblePlugin(
                "agent_adapters plugin call_observability must be an exact "
                "string: 'full', 'logical_only', or 'opaque'"
            )


def _safe_entry_point_identity(entry_point: object, index: int) -> str:
    """Return an identity without relying on untrusted repr or descriptors."""

    try:
        name = getattr(entry_point, "name", None)
    except Exception:
        name = None
    if type(name) is str and name:
        return f"name={name[:128]!r}, index={index}"
    return f"index={index}"


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
            for index, entry_point in enumerate(provider(group=group)):
                try:
                    loader = getattr(entry_point, "load")
                    loaded = loader()
                except Exception as exc:
                    identity = _safe_entry_point_identity(entry_point, index)
                    raise IncompatiblePlugin(
                        f"{category} plugin entry point {identity} in group "
                        f"{group!r} failed to load"
                    ) from exc
                discovered[category].append(loaded)
        return cls.from_objects(**discovered)

    def _register(self, category: str, plugin: object) -> None:
        manifest = _validated_manifest(category, plugin)
        try:
            ref = PluginRef(
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.plugin_version,
            )
        except UntrustedPluginReference as exc:
            raise IncompatiblePlugin(
                f"{category} plugin has an invalid manifest reference"
            ) from exc

        _validate_contract(category, plugin)

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
    "DuplicateReferenceImplementation",
    "DuplicatePluginRegistration",
    "IncompatiblePlugin",
    "InvalidReferenceImplementation",
    "PluginRegistry",
    "PluginRegistryError",
    "PluginVersionMismatch",
    "ReferenceImplementationError",
    "ReferenceImplementationHashMismatch",
    "ReferenceImplementationRegistry",
    "ReferenceImplementationRole",
    "ReferenceImplementationRoleMismatch",
    "ReferenceImplementationVersionMismatch",
    "RegisteredReferenceImplementation",
    "UnknownReferenceImplementation",
    "UnknownPlugin",
]
