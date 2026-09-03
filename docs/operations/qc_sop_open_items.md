# QC/SOP open items

This file is the normative home for QC/SOP work that must remain visible after
the planning checklist was removed from the campaign document. An item is not
closed merely because a schema can represent it; the admission or execution
boundary must enforce it and a regression test must demonstrate failure on a
counterexample.

## Enforced in the repository

- **Campaign invalidation:** pre-freeze invalidation records reopen the named
  gate and its downstream suffix without deleting history. A retry-policy
  change must restart at `profile_admission`; post-freeze changes require a new
  campaign identity.
- **Typed Housing status:** development qualification and normative profile
  readiness are separate typed states. Only a normative `passed` state permits
  promotion.
- **QC artifact binding:** campaign and contributed-family admission resolve
  relative paths inside a declared evidence root, require the expected artifact
  type, recompute SHA-256 from the referenced bytes, bind family/version/profile
  identity, and check declared coverage.
- **External parity criteria:** each parity specification declares a pinned
  source, task, treatment, metric, original conclusion, and tolerance. The
  metric must name a real parity field and its comparison mode and tolerance
  must match that field exactly.
- **Contribution admission:** new families use isolated namespaces, closed
  action and observation schemas, byte-verified provider-free and human-QC
  evidence references, and finite resource-limit declarations. Those limits
  are retained in the registered plugin metadata.

## Remaining promotion blockers

### 1. Run and validate provider-free conformance at a trusted boundary

**Current boundary:** registration proves that a content-addressed artifact is
present and that its typed reference declares complete provider-free coverage.
It does not execute the conformance suite or parse and validate the report's
semantic result, so a contributor can still author both the artifact and its
coverage claim.

**Required closure:** CI or another trusted runner must execute the pinned
provider-free suite, emit a closed-schema result that binds the family source
and test-suite versions, and require an overall pass plus every declared case
receipt before producing admissible evidence. Until then, provider-free
evidence is audit material, not sufficient production admission.

### 2. Enforce contribution resource limits during execution

**Current boundary:** registration validates and retains finite ceilings for
wall time, logical actions, provider calls, input tokens, output tokens, and
cost. The generic execution path does not yet consume every one of those
counters or terminate a run when a contributed family's ceiling is reached.

**Required closure:** resolve the registered contribution metadata before
execution, meter all six resources across retries and tool/provider calls,
terminate with typed missingness or failure at the first exceeded limit, and add
counterexample tests for each ceiling. Until then, contributed families must not
run through the production or paid-provider path.

### 3. Authenticate human QC approval outside the contribution payload

**Current boundary:** admission proves that a present, content-addressed
approval artifact and its declared reviewer ID bind the exact contribution
digest. Repository code alone cannot prove that the claimed reviewer authored
the artifact or had approval authority.

**Required closure:** production admission must verify the approval against an
organization-controlled identity or signature mechanism and an authorized
reviewer list. Tests must reject an otherwise well-formed approval signed by an
unknown or unauthorized identity. Until that verifier exists, local approval
records are audit evidence, not sufficient production authorization.

## Promotion rule

The three remaining items above are hard blockers for externally contributed
families. They do not block provider-free development, built-in family tests,
or parity work, but no status report may translate those narrower passes into
production contribution approval.
