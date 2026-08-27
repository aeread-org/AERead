# Shared-runner portability contract

**Status:** core contract implemented; family adapters remain separate deliverables

**Scope:** define the smallest runner-owned surface that Housing, external refund, and a
future supply-chain case can share without merging their domain semantics or scores

## 1. Ownership boundary

The **shared runner owns** portable identifiers, versioned tool declarations, effect-aware
tool evidence, durable event/artifact storage, typed measurement leaves, and component-level
parity reports. The **family adapter owns** environment state, observation and action
semantics, tool implementations, canonical projections, estimands, verifier algorithms,
reference validity, and family scores.

A provider-specific tool loop is adapter-owned or harness-owned. The core exposes
`ToolRuntime`; it does not assume that OpenAI, Tau3, a simulator, or a supply-chain engine
formats tool calls the same way. The adapter converts its protocol into canonical calls and
results, while the core records and verifies them.

```text
provider or upstream harness
  -> family adapter parses one declared tool call
  -> ToolRuntime resolves the pinned ToolDefinition
  -> ToolInvocationRecord binds input, effect, result, and state evidence
  -> family verifier emits one or more MeasurementLeafSpec results
  -> ScoreEnvelope plus EvidenceSeal enters the receipt
  -> ParityReport proves upstream/legacy compatibility field by field
```

## 2. Runner-owned portable records

| Contract | Purpose |
|---|---|
| `is_exportable_id` | Restricts exported IDs to lower-case path/URL/rLLM-safe grammar; in particular, a case ID cannot contain rLLM's colon separator. |
| `ToolDefinition` | Pins tool ID, semantic version, read-only or mutating effect, input-schema hash, and idempotency declaration. |
| `ToolRuntime` | Resolves only declared tool bindings and sends every invocation through the evidence-first executor. |
| `ToolInvocationRecord` | Binds tool schema and argument hashes, effect, result, before/after state hashes, state-diff hash, known/unknown outcome, and failure condition. |
| `EvidenceSeal` | Commits the event and artifact roots after single-writer, resume, hash-chain, and filesystem-integrity checks. |
| `MeasurementLeafSpec` | Binds one estimand to one compatible semantic verifier/reference family and pinned scorer. |
| `ScoreEnvelope` | Retains the leaf, native-unit metrics, typed references, utilities/capture, validity, and evidence references. |
| `ParitySpec` / `ParityReport` | Compares declared upstream and adapter projection fields exactly or with a predeclared numeric tolerance. |

The measurement layer retains a vector and has **no universal scalar**. A canonical refund
pass, bounded housing utility, and supply-chain cost or service level remain distinct
scientific claims even though they share receipts and analysis infrastructure.

## 3. Family mappings

| Family | Primary semantic route | Tool/state route | Required parity fields before publication |
|---|---|---|---|
| `housing_v1` | `objective_reference`: realized social welfare plus separately scoped feasible witness, naive comparison baseline, and full-information allocation upper bound | Native phase actions; no external business-tool loop is required for the current case | terminal allocation, per-seat utility/capture, typed references, validity, receipt admission, and state-and-score replay |
| `tau3_retail` | `canonical_reference`: terminal database equivalence; optional `rule_constraint` temporal leaves; upstream judge-dependent components remain separate | Bind pinned Tau3 retail tools through `ToolDefinition`; mutating tools require a canonical database `state_reader` | initial DB, ordered calls/results, final DB, state diff, DB component, communication component, pinned judge artifact/configuration, and upstream aggregate |
| `supply_chain_v1` | usually a vector: `rule_constraint` for authorization/order timing plus `objective_reference` or `comparative` for cost, fill rate, delay, or welfare | Bind inventory, quote, purchase-order, shipment, and cancellation tools through the same `ToolRuntime`; every mutating tool needs a canonical ledger snapshot | initial inventory/orders, ordered calls/results, final inventory/order state, constraint vector, objective inputs/value, and any upstream aggregate |

`supply_chain_v1` is a reserved adapter shape, not a claim that a source suite has already
been selected or implemented. Its exact estimands and parity fields must be frozen only
after the source environment, task population, and verifier semantics are pinned.

## 4. Adapter interface

Each tool-capable adapter supplies:

1. a tuple of pinned `ToolDefinition` records;
2. one implementation binding per definition;
3. a canonical `state_reader` for every mutating tool, and optionally for read-only tools
   when non-mutation should be checked;
4. a parser that maps its provider/upstream call representation to `tool_id` and canonical
   arguments;
5. one or more `MeasurementLeafSpec` declarations and pinned verifier/scorer
   implementations;
6. canonical upstream and adapted projections plus a versioned `ParitySpec`;
7. a receipt projection that includes the tool-manifest hash, parity-report hash, and
   `EvidenceSeal` roots.

A tool failure after a partial mutation must be raised as a known tool failure only when the
adapter can take a valid after-state snapshot. Interruption with uncertain external outcome
remains `outcome_unknown`; a momentary observation must not be promoted to a final-state
claim.

## 5. Build and review gates

1. Land the core portability contracts on top of shared-runner R4; do not introduce the
   parallel `aeread.runner` / `aeread.sdk.v1` kernel from the comparison branch.
2. **Implemented on the Housing stack:** rebase the Housing adapter, express its reported
   measurements through typed leaves, and emit validated receipts while keeping Housing
   semantics in the Housing PR.
3. Express Exchange old/new comparisons as a `ParitySpec` and close the complete parity
   matrix before treating the generic path as a replacement.
4. Implement the pinned Tau3 retail adapter and the 18-task pilot. A provider-free replay
   must pass all deterministic fields before paid model runs.
5. Select and pin a supply-chain source environment. Implement its adapter only after its
   state canonicalization, tool-effect declarations, primary estimands, cluster, and parity
   fields are reviewed.
6. Add provider-specific tool-loop harnesses as thin consumers of `ToolRuntime`; do not put
   provider branching or domain branching in the shared kernel.

The core contracts make both adapters feasible, but they do not by themselves make either
external benchmark runnable. Runtime readiness requires the family-specific bindings,
upstream fixtures, parity suite, scorer bridge, and receipt integration described above.
