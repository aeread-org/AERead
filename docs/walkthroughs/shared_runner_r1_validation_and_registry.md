# Walkthrough: Shared-runner R1 validation and plugin resolution

> **Status (2026-09-02): Complete.** The focused R1 schema and registry contracts pass in the
> assessed checkout. See the [roadmap implementation status](shared_runner_architecture_roadmap.md#implementation-status--2026-09-02)
> for verification scope and downstream blockers.

**Entry point:** `src/aeread/shared_runner/schemas.py:parse_authoring_record()` (line 1170)

**Trigger:** Library code passes one decoded JSON, YAML, or TOML mapping to
`parse_authoring_record()`. This walkthrough follows the `aeread.family/0.1` branch from a
Housing authoring fixture to exact plugin resolution.

**Files involved:**

- `src/aeread/shared_runner/schemas.py` — validates and freezes the eight R1 authoring record
  kinds.
- `src/aeread/shared_runner/registry.py` — admits complete, explicitly trusted family plugins
  and resolves an exact family/version/plugin identity.
- `tests/test_shared_runner_schemas.py` — supplies Housing-shaped fixtures and exercises the
  success and fail-closed paths.

**What changes:** Schema parsing reads an in-memory mapping and returns an immutable record. It
does not touch the filesystem, network, provider, environment, or plugin. `PluginRegistry.register()`
mutates one process-local dictionary; resolution is read-only. No phase is scheduled and no
case is executed in R1.

---

## Step 1: The caller supplies authored family data

`tests/test_shared_runner_schemas.py:L30-L50`

```python
def family_data() -> dict:
    return {
        "spec_version": "aeread.family/0.1",
        "family": {
            "id": "housing_v1",
            "version": "1.0.0",
            "plugin_id": "aeread.housing_v1",
        },
        "environment": {
            "topology": "market_with_private_preferences",
            "phase_specs": ["contact_v1", "respond_v1", "commit_v1"],
            "needs_tools": False,
            "needs_sandbox": False,
        },
        "roles": {
            "tenant": {"testable": True, "scripted_policies": []},
            "landlord": {
                "testable": False,
                "scripted_policies": ["fixed_landlord_v1"],
            },
        },
```

This data says what protocol family exists. It does not assign a model, request a run, or
contain executable plugin code. The `plugin_id` is an identity claim that the trusted registry
must later match exactly.

**Calls →** Step 2 through `parse_authoring_record(family_data())`.

**Data flow:** mutable Python `dict` → generic authoring-record parser.

**Danger zone:** A file decoder is outside R1. The caller must decode JSON, YAML, or TOML into
a mapping before entering this path.

---

## Step 2: Dispatch by the exact schema version

`src/aeread/shared_runner/schemas.py:L1170-L1181`

```python
def parse_authoring_record(value: Any) -> AuthoringRecord:
    """Parse one strict R1 record by its exact ``spec_version`` discriminator."""
    data = _as_mapping(value, "authoring record")
    if "spec_version" not in data:
        raise AuthoringValidationError("authoring record is missing spec_version")
    spec_version = _string(data["spec_version"], "authoring record.spec_version")
    record_type = _RECORD_TYPES.get(spec_version)
    if record_type is None:
        raise AuthoringValidationError(
            f"unsupported authoring record spec_version: {spec_version!r}"
        )
    return record_type.from_dict(data)
```

The parser refuses to guess a record kind. `aeread.family/0.1` resolves to
`FamilyManifest`; an absent or unknown discriminator fails before any plugin or runner logic
can execute.

**Calls →** `FamilyManifest.from_dict()` in Step 3.

**Data flow:** generic mapping + exact discriminator → one concrete record parser.

---

## Step 3: Reject missing and unknown shared fields

`src/aeread/shared_runner/schemas.py:L34-L48`

```python
def _fields(
    value: Any,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    path: str,
) -> Mapping[str, Any]:
    data = _as_mapping(value, path)
    missing = sorted(required - set(data))
    if missing:
        raise AuthoringValidationError(f"{path} is missing required fields: {missing}")
    unexpected = sorted(set(data) - required - optional)
    if unexpected:
        raise AuthoringValidationError(f"{path} has unexpected fields: {unexpected}")
    return data
```

Every shared object uses this boundary. A typo such as `plugn_id` cannot silently survive as
unused configuration, and a future schema field cannot be consumed by an older implementation
without a version change.

**Calls →** exact version, role, measurement, scorer, and generator validation in Step 4.

**Data flow:** untrusted mapping → mapping with a known field set.

---

## Step 4: Construct the immutable family record

`src/aeread/shared_runner/schemas.py:L334-L380`

```python
@dataclass(frozen=True, slots=True)
class FamilyManifest:
    SPEC_VERSION: ClassVar[str] = "aeread.family/0.1"

    spec_version: str
    family: FamilyIdentity
    environment: EnvironmentSpec
    roles: Mapping[str, RoleSpec]
    measurement: MeasurementDeclaration
    scoring: ScoringSpec
    generator: GeneratorSpec | None

    @classmethod
    def from_dict(cls, value: Any) -> "FamilyManifest":
        data = _fields(
            value,
            required={"spec_version", "family", "environment", "roles", "measurement", "scoring"},
            optional={"generator"},
            path="FamilyManifest",
        )
        _require_spec_version(data["spec_version"], cls.SPEC_VERSION, "FamilyManifest")
        role_data = _as_mapping(data["roles"], "FamilyManifest.roles")
        if not role_data:
            raise AuthoringValidationError("FamilyManifest.roles must not be empty")
        roles = MappingProxyType(
            {
                _identifier(role_id, "FamilyManifest.roles key"): RoleSpec.from_dict(
                    role, f"FamilyManifest.roles.{role_id}"
                )
                for role_id, role in role_data.items()
            }
        )
        if not any(role.testable for role in roles.values()):
            raise AuthoringValidationError("FamilyManifest.roles needs at least one testable role")
        return cls(
            spec_version=cls.SPEC_VERSION,
            family=FamilyIdentity.from_dict(data["family"], "FamilyManifest.family"),
            environment=EnvironmentSpec.from_dict(data["environment"], "FamilyManifest.environment"),
            roles=roles,
            measurement=MeasurementDeclaration.from_dict(data["measurement"], "FamilyManifest.measurement"),
            scoring=ScoringSpec.from_dict(data["scoring"], "FamilyManifest.scoring"),
            generator=(
                None
                if data.get("generator") is None
                else GeneratorSpec.from_dict(data["generator"], "FamilyManifest.generator")
            ),
        )
```

The nested parsers enforce strict types and identifiers. `frozen=True` prevents rebinding the
record fields; `MappingProxyType` prevents later mutation of the role table. At least one role
must be testable, so the authored object cannot describe a benchmark with no unit under test.

**Calls →** Step 5 for typed measurement validation, then returns to the caller.

**Data flow:** validated shared sections → immutable `FamilyManifest`.

**Danger zone:** R1 validates each record independently. It does not yet prove that referenced
phase, scorer, baseline, or generator implementations exist; R2 preflight must resolve and pin
those identities.

---

## Step 5: Preserve the measurement kind instead of assuming AER

`src/aeread/shared_runner/schemas.py:L249-L279`

```python
    @classmethod
    def from_dict(cls, value: Any, path: str = "measurement") -> "MeasurementDeclaration":
        optional = {
            "optimum_lower_bound",
            "comparison_baseline",
            "optimum_upper_bound",
            "optimum_upper_bound_kind",
            "bound_status",
            "outcome_support",
        }
        data = _fields(
            value,
            required={"primary_estimand", "measurement_kind", "direction"},
            optional=optional,
            path=path,
        )
        return cls(
            primary_estimand=_identifier(data["primary_estimand"], f"{path}.primary_estimand"),
            measurement_kind=_enum(
                data["measurement_kind"],
                f"{path}.measurement_kind",
                {"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"},
            ),
            direction=_enum(data["direction"], f"{path}.direction", {"maximize", "minimize", "none"}),
            optimum_lower_bound=_optional_string(data.get("optimum_lower_bound"), f"{path}.optimum_lower_bound"),
            comparison_baseline=_optional_string(data.get("comparison_baseline"), f"{path}.comparison_baseline"),
            optimum_upper_bound=_optional_string(data.get("optimum_upper_bound"), f"{path}.optimum_upper_bound"),
            optimum_upper_bound_kind=_optional_string(data.get("optimum_upper_bound_kind"), f"{path}.optimum_upper_bound_kind"),
            bound_status=_optional_string(data.get("bound_status"), f"{path}.bound_status"),
            outcome_support=_optional_string(data.get("outcome_support"), f"{path}.outcome_support"),
        )
```

This is the first concrete break from the old Exchange-only adapter. Housing can declare an
`optimizable_outcome`; refund can declare `property_or_answer`; neither is forced into
`w_real / denominator` merely because rLLM expects a reward.

**Calls →** The validated manifest can now be admitted to a trusted registry in Step 6.

**Data flow:** authored measurement declaration → typed family metadata retained for later plan
resolution and scoring.

**Danger zone:** The combination is syntactically validated here, but proof that a claimed bound
or comparison reference is valid belongs to measurement preflight and the family conformance
suite.

---

## Step 6: Admit only a complete trusted plugin

`src/aeread/shared_runner/registry.py:L62-L86`

```python
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
```

Registration is explicit: there is no package scan, dynamic import, or last-one-wins override.
The plugin must expose all family-owned boundaries—state initialization, phases, observation,
parsing, legality, transition, termination, outcome, scoring, references, and generation.

**Mutation:** inserts one `RegisteredPlugin` into the process-local `_plugins` dictionary.

**Calls →** Step 7 when the resolver requests the manifest's exact implementation.

**Data flow:** immutable `FamilyManifest` + trusted plugin object → exact registry entry keyed by
`(family_id, family_version)`.

**Danger zone:** R1 checks that hooks are callable, not that their signatures or behavior satisfy
the protocol. The R3 provider-free conformance suite must exercise those contracts.

---

## Step 7: Resolve the exact family, version, and plugin identity

`src/aeread/shared_runner/registry.py:L88-L109`

```python
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
```

Resolution fails closed for an unknown version or a mismatched plugin ID. A Housing manifest
cannot accidentally receive the Exchange implementation, and a new family version cannot reuse
an older implementation implicitly.

**Returns →** the trusted plugin object. In R2, the resolver will pin its implementation identity
inside the immutable `RunPlan`; in R3, the scheduler will call its phase hooks.

**Data flow:** exact manifest identity → exact executable plugin object.

---

## Step 8: Regression tests enforce the boundary

`tests/test_shared_runner_schemas.py:L354-L378`

```python
def test_registry_resolves_only_exact_trusted_family_version_and_plugin() -> None:
    manifest = FamilyManifest.from_dict(family_data())
    plugin = CompleteHousingPlugin()
    registry = PluginRegistry()
    registry.register(manifest, plugin)

    assert registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1") is plugin
    assert registry.resolve_manifest(manifest) is plugin

    with pytest.raises(PluginResolutionError, match="not registered"):
        registry.resolve("housing_v1", "2.0.0", "aeread.housing_v1")
    with pytest.raises(PluginResolutionError, match="plugin_id"):
        registry.resolve("housing_v1", "1.0.0", "aeread.other")


def test_registry_rejects_duplicate_or_incomplete_plugins() -> None:
    manifest = FamilyManifest.from_dict(family_data())
    registry = PluginRegistry()
    registry.register(manifest, CompleteHousingPlugin())
    with pytest.raises(DuplicatePluginError, match="already registered"):
        registry.register(manifest, CompleteHousingPlugin())

    incomplete = object()
    with pytest.raises(IncompletePluginError, match="validate_payload"):
        PluginRegistry().register(manifest, incomplete)
```

The tests cover both the successful identity path and the important failure branches. They do
not claim that Housing can execute yet; the fixture plugin is deliberately inert.

---

## Danger Zones

| # | Location | Risk | Mitigation |
|---|---|---|---|
| 1 | `schemas.py:L1170-L1181` | A caller may treat decoded input as validated without calling the dispatcher. | Public runner entry points must accept validated R1 records or call `parse_authoring_record()` themselves. |
| 2 | `schemas.py:L148-L163` | Family payload structure is intentionally opaque to shared schemas. | The resolved family plugin must call `validate_payload()` during R2 preflight before any external call. |
| 3 | `schemas.py:L249-L279` | A syntactically named bound may not be a valid bound for the declared estimand. | Measurement preflight and executable reference fixtures must validate meaning and provenance. |
| 4 | `registry.py:L65-L73` | Callable presence does not prove correct signatures, determinism, or noninterference. | R3 conformance tests exercise every hook with provider-free fixtures. |
| 5 | `registry.py:L81-L86` | The registry stores a live plugin object by reference. | R2 must record implementation version/hash before execution; deployment registration must finish before plan sealing. |
| 6 | R1 boundary | Record references are not yet reconciled across family, case, suite, profile, and run objects. | R2 resolves all references and refuses to emit a `RunPlan` when any identity is missing or inconsistent. |
| 7 | R1 boundary | No phase scheduler, evidence log, receipt, replay, or Housing transition is executed. | Do not describe PR #9 as a runnable shared runner; those are R3–R7 gates. |

## Invariants

- Every authored shared record has one exact supported `spec_version`.
- Missing and unknown shared fields fail validation; there is no silent schema drift.
- Strict integers reject booleans, numeric inputs must be finite, and IDs/digests follow their
  declared formats.
- A `CaseManifest` contains the world and seats, never model assignment.
- Returned records and their shared mappings are immutable.
- A family/version key has at most one registered plugin.
- Resolution requires exact agreement on family ID, family version, and plugin ID.
- Parsing and resolution perform no provider call, tool call, filesystem write, phase transition,
  or scoring operation.
- R1 output is authored intent. Only a future sealed `RunPlan` is benchmark execution truth.
