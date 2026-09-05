# Walkthrough: Shared-runner R2 deterministic plan resolution

> **Status (2026-09-02): Complete.** Deterministic resolution, canonical plan identity, exact
> implementation pins, and pre-execution plan publication pass the focused contracts. See the
> [roadmap implementation status](shared_runner_architecture_roadmap.md#implementation-status--2026-09-02).

R2 turns the immutable R1 authoring records into one sealed `RunPlan`. It resolves every
cross-record reference, verifies case content identity, pins every executable dependency,
validates family-owned payloads, expands the requested experiment into `PlanCell` records,
and writes canonical bytes before any provider or tool call.

The implementation is in `src/aeread/shared_runner/run/resolver.py`; its executable contract is
in `tests/test_shared_runner_resolver.py`.

## Resolution path

```text
R1 records + implementation pins + trusted PluginRegistry
  -> reconcile suite, case, family, block, analysis, profile, and run references
  -> verify normalized case content_sha256 values
  -> require exact family-plugin, scorer, reference, generator, harness, and runtime pins
  -> resolve the exact family plugin and validate each selected case payload
  -> expand case x block x sampling seed x block repetition x sampling replicate
  -> derive cluster, pair, cell, and plan identities from canonical content
  -> verify and durably publish the immutable RunPlan
```

All input ordering that is semantically declared by the suite or run is retained. Caller
container order that has no declared meaning, such as the order of supplied profiles or pins,
is normalized. Reordering those inputs therefore produces byte-identical plans.

## Sealed identities

`case_content_sha256()` parses a case through the R1 schema so defaults are normalized, removes
the self-referential digest field, and hashes canonical UTF-8 JSON. Resolution rejects a changed
case before calling a family plugin.

Each `ImplementationPin` records a component ID, kind, version, and SHA-256 digest. R2 requires
pins for every selected family plugin, scorer, oracle/reference provider, generator, agent
harness, and runtime implementation. Missing, extra, duplicate, or incorrectly typed pins fail
preflight.

Each `PlanCell` records the selected case and family identity, evaluation block, sampling and
analysis identities, world and sampling seeds, both repetition counters, cluster and pairing
metadata, seat-to-profile assignment, execution mode, and logical-action budget. Its `cell_id`
is derived from all those fields.

The `RunPlan` embeds the normalized selected records, implementation pins, input digests, and
cells. Its `plan_sha256` is derived from all plan content except its self-referential ID and
digest; `run_plan_id` is derived from that digest.

## Failure ordering

R2 performs shared validation in this order:

1. Check record types, unique identities, and cross-record references.
2. Verify selected case content hashes.
3. Verify that the implementation-pin set is exact.
4. Resolve the exact registered family implementation.
5. Ask the family plugin to validate its opaque case payload.
6. Expand and seal cells.

This ordering keeps malformed or changed shared inputs from reaching case-owned plugin code and
keeps all provider calls outside resolution.

## Durable write rule

`write_run_plan()` re-verifies the complete plan, writes canonical bytes to a temporary file,
flushes them, and publishes the destination without overwriting an existing file. A repeated
attempt against the same destination fails instead of silently replacing benchmark truth.

## Exact R2 boundary

R2 is enough to answer: "What precisely would this experiment run?" It is not enough to run it.

- R3 consumes `PlanCell` records in a provider-free phase scheduler and produces transition and
  termination behavior.
- R4 supplies model/harness adapters and normalized attempt accounting.
- Later stages add durable evidence, receipts, replay, scorers, and production family adapters.

Therefore the first end-to-end R2 check costs no model tokens. A paid Housing run is honest only
after the R3 scheduler and an R4 adapter exist; until then, a model call would bypass the shared
runner contract it is supposed to test.
