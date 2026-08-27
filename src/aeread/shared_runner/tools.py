"""Versioned tool manifests and bindings for tool-capable case adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from .execution import EvidenceStore, ToolExecutor, ToolInvocationRecord
from .resolver import canonical_json_bytes
from .schemas import is_exportable_id


_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)


class ToolContractError(ValueError):
    """A tool manifest or runtime binding is incomplete or inconsistent."""


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ToolContractError("tool schema keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        canonical_json_bytes(value)
        return value
    raise ToolContractError("tool schema must contain only canonical JSON values")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_id: str
    tool_version: str
    effect: str
    input_schema: Mapping[str, Any]
    idempotency_supported: bool
    schema_sha256: str = field(init=False)
    definition_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not is_exportable_id(self.tool_id):
            raise ToolContractError("tool_id must be an exportable identifier")
        if not isinstance(self.tool_version, str) or _SEMVER_RE.fullmatch(self.tool_version) is None:
            raise ToolContractError("tool_version must be an exact semantic version")
        if self.effect not in {"read_only", "mutating"}:
            raise ToolContractError("tool effect must be read_only or mutating")
        if type(self.idempotency_supported) is not bool:
            raise ToolContractError("idempotency_supported must be a boolean")
        if not isinstance(self.input_schema, Mapping):
            raise ToolContractError("input_schema must be an object")
        schema = _freeze_json(self.input_schema)
        schema_sha256 = hashlib.sha256(canonical_json_bytes(schema)).hexdigest()
        object.__setattr__(self, "input_schema", schema)
        object.__setattr__(self, "schema_sha256", schema_sha256)
        object.__setattr__(
            self,
            "definition_sha256",
            hashlib.sha256(
                canonical_json_bytes(
                    {
                        "tool_id": self.tool_id,
                        "tool_version": self.tool_version,
                        "effect": self.effect,
                        "input_schema_sha256": schema_sha256,
                        "idempotency_supported": self.idempotency_supported,
                    }
                )
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ToolBinding:
    definition: ToolDefinition
    implementation: Callable[[Mapping[str, Any]], Awaitable[Any]]
    state_reader: Callable[[], Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ToolDefinition):
            raise ToolContractError("definition must be a ToolDefinition")
        if not callable(self.implementation):
            raise ToolContractError("tool implementation must be callable")
        if self.state_reader is not None and not callable(self.state_reader):
            raise ToolContractError("state_reader must be callable")


class ToolRuntime:
    """Resolve only declared tools, then delegate effect evidence to ToolExecutor."""

    def __init__(self, evidence: EvidenceStore, bindings: tuple[ToolBinding, ...]) -> None:
        if not isinstance(evidence, EvidenceStore):
            raise ToolContractError("evidence must be an EvidenceStore")
        if not isinstance(bindings, tuple):
            raise ToolContractError("bindings must be a tuple")
        indexed: dict[str, ToolBinding] = {}
        for binding in bindings:
            if not isinstance(binding, ToolBinding):
                raise ToolContractError("bindings must contain only ToolBinding records")
            definition = binding.definition
            if definition.tool_id in indexed:
                raise ToolContractError(f"duplicate tool definition: {definition.tool_id}")
            if definition.effect == "mutating" and binding.state_reader is None:
                raise ToolContractError(
                    f"mutating tool {definition.tool_id!r} requires a state_reader"
                )
            indexed[definition.tool_id] = binding
        self.evidence = evidence
        self._bindings = MappingProxyType(indexed)
        self._executor = ToolExecutor(evidence)
        manifest = tuple(
            {
                "tool_id": binding.definition.tool_id,
                "definition_sha256": binding.definition.definition_sha256,
            }
            for _, binding in sorted(indexed.items())
        )
        self.manifest_sha256 = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()

    def definition(self, tool_id: str) -> ToolDefinition:
        try:
            return self._bindings[tool_id].definition
        except KeyError as error:
            raise ToolContractError(f"undeclared tool: {tool_id!r}") from error

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            binding.definition for _, binding in sorted(self._bindings.items())
        )

    async def invoke(
        self,
        *,
        action_attempt_id: str,
        tool_id: str,
        arguments: Mapping[str, Any],
    ) -> tuple[Any, ToolInvocationRecord]:
        try:
            binding = self._bindings[tool_id]
        except KeyError as error:
            raise ToolContractError(f"undeclared tool: {tool_id!r}") from error
        definition = binding.definition
        return await self._executor.invoke(
            action_attempt_id=action_attempt_id,
            tool_id=definition.tool_id,
            tool_version=definition.tool_version,
            arguments=arguments,
            implementation=binding.implementation,
            idempotency_supported=definition.idempotency_supported,
            effect=definition.effect,
            tool_schema_sha256=definition.schema_sha256,
            state_reader=binding.state_reader,
        )


__all__ = [
    "ToolBinding",
    "ToolContractError",
    "ToolDefinition",
    "ToolRuntime",
]
